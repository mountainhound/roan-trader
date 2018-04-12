from flask import Flask, request, jsonify, url_for
import requests
from bandwidth import messaging
from trading_view_bot import gdax_bot
import gdax
import json
import datetime
import pytz
import time
from decimal import *
import signal
import sys
import os
'''
import logging
logging.basicConfig()
'''
import roan_settings as settings
from flask_apscheduler import APScheduler


app = Flask(__name__)
auth_client = gdax.AuthenticatedClient(settings.GDAX_API_KEY, settings.GDAX_PRIVATE_KEY, settings.GDAX_PASSPHRASE)

def maintenance(): 
	try: 
		bot_dict = app.config['GDAX_BOT_DICT']
		for key,bot in bot_dict.items(): 
			try: 
				bot.orderbook_conn()
				bot.stop_limit()
			except Exception as e: 
				print e
			except ValueError as e: 
				print e
		print {"message":"Maintenance Check"}
	
	except Exception as e: 
		print e
	except ValueError as e: 
		print e

class Config(object):
	JOBS = [
			{
				'id': 'GDAX Bot Maintenance',
				'func': maintenance,
				'trigger': 'interval',
				'seconds': 60,
				'max_instances': 200
			}
	]

	SCHEDULER_API_ENABLED = True



def sigint_handler(signum, frame):
	bot_dict = app.config.get('GDAX_BOT_DICT')
	if bot_dict:
		for key,bot in bot_dict.items(): 
			bot.orderbook.close()
			print "closing orderbook"

	time.sleep(1)
	sys.exit()
 
signal.signal(signal.SIGINT, sigint_handler)

def create_app(gdax_bot_dict):
	app.config['GDAX_BOT_DICT'] = gdax_bot_dict
	app.config['LOG_PATH'] = "order-log.json"
	app.config['STOP_FLAG'] = False
	app.config['STOP_LIMIT'] = .92
	app.config['MESSAGE_API'] = messaging.Client(settings.BANDWIDTH_USER, settings.BANDWIDTH_TOKEN, settings.BANDWIDTH_SECRET)
	app.config['ROOT_PHONE'] = settings.ROOT_NUMBER
	app.config['INIT_EQUIV_FIAT'] = equivalent_fiat(app.config['GDAX_BOT_DICT'])
	app.config.from_object(Config())
	print "INIT FIAT SUM: {}".format(app.config['INIT_EQUIV_FIAT'])
	return app

def text_message(message_api,message_body):

	message_id = message_api.send_message(from_ = '+1{}'.format(settings.ORIGIN_NUMBER),
                              to = '+1{}'.format(settings.ROOT_NUMBER),
                              text = message_body)

def equivalent_fiat(bot_dict):
	equiv_fiat_sum = Decimal(0.00)
	fiat_balance = Decimal(0.00)
	for coin_id,bot in bot_dict.items(): 
		price = bot.get_price()
		if price: 
			time.sleep(.2)
			coin_balance,fiat_balance = bot.get_balances(pending_flag = False)
			equiv_fiat_sum += Decimal(coin_balance * price).quantize(Decimal('.01'), rounding=ROUND_DOWN)
			fiat_balance = fiat_balance
			time.sleep(.5)
		else: 
			return None

	total_sum = fiat_balance + equiv_fiat_sum
	
	return round(total_sum,2)

def logger(log_path,log_message):
	utc_now = pytz.utc.localize(datetime.datetime.utcnow())
	#pst_now = utc_now.astimezone(pytz.timezone("America/Los_Angeles"))
	ct_now = utc_now.astimezone(pytz.timezone("America/Chicago"))
	log_message['central-timezone'] = str(ct_now.isoformat())
	
	with open(log_path,'a+') as f:
		json.dump(log_message, f)
		f.write('\n')

def check_message(message_id):
	message_id = message_id.replace('<','').replace('>','')
	ret =  requests.get(
		"{}/events".format(settings.MAILGUN_API_URL),
		auth=("api", settings.MAILGUN_API_KEY),
		params={"message-id": message_id})
	#Check if return was valid if not then do not place trade
	print "mailgon status code: {}".format(ret.status_code)
	if ret.status_code == 200:
		print "Email received Checking.."
		data =  ret.json()
		for event in  data.get('items'):
			if event.get('delivery-status'):
				if event.get('delivery-status').get('attempt-no') > 1:
					print event.get('delivery-status').get('attempt-no')
					return False
		return True

	return False

@app.route('/sms', methods=['POST'])
def sms():
	app.config['ROOT_FLAG'] = False
	
	data =  request.data
	data = json.loads(data)
	message_body = data.get('text').lower()
	number = data.get('from')
	root_number = app.config['ROOT_PHONE']
	message_api = app.config['MESSAGE_API']


	if root_number in number:
		print "HELLO PARKER"
	else: 
		return "NOT AUTHORIZED", 403

	bot_dict = app.config['GDAX_BOT_DICT']
	print message_body

	if "shutdown" in message_body or "stop" in message_body:
		print "SHUTTING DOWN BOT"
		text_message(message_api,"SHUTTING DOWN BOT") 
		app.config['STOP_FLAG'] = True

	if "shutdown" in message_body and "sell" in message_body.lower():
		print "SHUTTING DOWN AND SELLING ALL"
		text_message(message_api,"SHUTTING DOWN AND SELLING ALL") 
		app.config['STOP_FLAG'] = True
		for key,value in gdax_bot_dict.items():
				bot = value
				bot.run(short_sell_flag = True)

	if "resume" in message_body: 
		print "RESUMING BOT"
		text_message(message_api,"RESUMING BOT") 
		app.config['STOP_FLAG'] = False

	if "reset" in message_body and "init" in message_body and "fiat" in message_body: 
		app.config['INIT_EQUIV_FIAT'] = equivalent_fiat()
		if "resume" in message_body:
			app.config['STOP_FLAG'] = False

	if "status" in message_body: 
		total_fiat = equivalent_fiat(bot_dict)
		text = "Init_Fiat_Balance: {} \nEquiv_Fiat_Balance: {} \n Stop_Flag: {} \n\n\n".format(app.config['INIT_EQUIV_FIAT'],total_fiat,app.config['STOP_FLAG'])
		for coin_id,bot in bot_dict.items():
			equiv_fiat,coin_balance = bot.get_equivalent_fiat()
			text += 'Coin_ID: {} \n Price: {} \n Coin_Balance_Value: {} \n Coin_Balance: {} \n Short_Flag: {} \n Long_Flag: {} \n\n'.format(bot.coin_id,bot.get_price(),equiv_fiat,coin_balance,bot.short_flag,bot.long_flag)
		text_message(message_api,text)

	if "short" in message_body and "buy" in message_body:
		for key,bot in bot_dict.items(): 
			if key in message_body:
				bot.run(short_buy_flag = True)

	if "short" in message_body and "sell" in message_body:
		for key,bot in bot_dict.items(): 
			if key in message_body:
				bot.run(short_sell_flag = True)

	if "long" in message_body and "buy" in message_body:
		for key,bot in bot_dict.items(): 
			if key in message_body:
				bot.run(long_buy_flag = True)

	if "long" in message_body and "sell" in message_body:
		for key,bot in bot_dict.items(): 
			if key in message_body:
				bot.run(long_sell_flag = True)

	if "long" in message_body and "flag":
		for key,bot in bot_dict.items(): 
			if key in message_body:
				if "true" in message_body:
					bot.long_flag = True
				elif "false" in message_body:
					bot.long_flag = False

	if "short" in message_body and "flag":
		for key,bot in bot_dict.items(): 
			if key in message_body:
				if "true" in message_body:
					bot.short_flag = True
				elif "false" in message_body:
					bot.short_flag = False

	return str(message_body)

@app.route('/email', methods=['POST'])
def email():
	message_id = request.form.get('Message-Id')
	print message_id
	message_body =  request.form.get('subject').lower()
	
	if not check_message(message_id):
		return jsonify({'message':'Email was a retry and was discarded'})

	bot_dict = app.config['GDAX_BOT_DICT']
	log_path = app.config['LOG_PATH']
	message_api = app.config['MESSAGE_API']
	print message_body

	STOP_FLAG = app.config['STOP_FLAG']
	equiv_fiat = None
	init_fiat = None

	stop_flag = stop_check()

	if stop_flag:
		app.config['STOP_FLAG'] = True

	STOP_FLAG = app.config['STOP_FLAG']


	if "short" in message_body and "buy" in message_body:
		if not STOP_FLAG:
			for key,bot in bot_dict.items(): 
				if key in message_body:
					equiv_fiat,coin_balance,fiat_balance,price,buy_flag,sell_flag = bot.run(short_buy_flag = True)
					log_text = {"price":float(price),"coin_id":key,"message":message_body,"method":"short buy"}
					
					if buy_flag and bot.pending_order:
						logger(log_path,log_text)
						text_message(message_api,str(log_text))

	if "short" in message_body and "sell" in message_body:
		if not STOP_FLAG:
			for key,bot in bot_dict.items(): 
				if key in message_body:
					equiv_fiat,coin_balance,fiat_balance,price,buy_flag,sell_flag = bot.run(short_sell_flag = True)
					log_text = {"price":float(price),"coin_id":key,"message":message_body,"method":"short sell"}
					
					if sell_flag and bot.pending_order:
						logger(log_path,log_text)
						text_message(message_api,str(log_text))

	if "long" in message_body and "buy" in message_body:
		if not STOP_FLAG:
			for key,bot in bot_dict.items(): 
				if key in message_body:
					equiv_fiat,coin_balance,fiat_balance,price,buy_flag,sell_flag = bot.run(long_buy_flag = True)
					log_text = {"price":float(price),"coin_id":key,"message":message_body,"method":"long buy"}
					
					if buy_flag and bot.pending_order:
						logger(log_path,log_text)
						text_message(message_api,str(log_text))

	if "long" in message_body and "sell" in message_body:
		if not STOP_FLAG:
			for key,bot in bot_dict.items(): 
				if key in message_body:
					equiv_fiat,coin_balance,fiat_balance,price,buy_flag,sell_flag = bot.run(long_sell_flag = True)
					log_text = {"price":float(price),"coin_id":key,"message":message_body,"method":"long sell"}
					
					if sell_flag and bot.pending_order:
						logger(log_path,log_text)
						text_message(message_api,str(log_text))

	return str(message_body)

def stop_check():
	with app.app_context():
		print "Check equivalent balance"
		bot_dict = app.config['GDAX_BOT_DICT']
		init_fiat = app.config['INIT_EQUIV_FIAT']
		total_fiat = equivalent_fiat(bot_dict)
		stop_limit = app.config['STOP_LIMIT']

		if total_fiat: 
			if total_fiat < init_fiat * stop_limit: 
				app.config['STOP_FLAG'] = True
				text = 'GDAX Bot initiated stop limit Equivilent_Fiat:{} Init_Fiat:{}'.format(equiv_fiat,init_fiat)
				message_api = app.config['MESSAGE_API']
				text_message(message_api,text)
				print text
				return True
		return False

if __name__ == '__main__':
	coin_ids = settings.COIN_LIST
	gdax_bot_dict = {}
	
	for coin_id in coin_ids: 
		product_id = coin_id + "-USD"
		gdax_bot_dict[coin_id.lower()] = gdax_bot(coin_id,product_id,auth_client)

	app = create_app(gdax_bot_dict)

	scheduler = APScheduler()
	scheduler.init_app(app)
	scheduler.start()

	http_server = WSGIServer(('',5000),app)
	http_server.serve_forever()