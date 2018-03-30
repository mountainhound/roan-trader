import gdax 
import time
import os
import numpy as np
import datetime
import dateutil.parser 
from dateutil.tz import *
from decimal import *
import threading
import Queue as queue

class gdax_bot(): 
	def __init__ (self,coin_id,product_id,auth_client):
		print "Initializing GDAX Bot PRODUCT: {}".format(product_id)

		self.auth_client = auth_client
		self.pc = gdax.PublicClient()
		self.coin_id = coin_id
		self.product_id = product_id
		self.orderbook = gdax.OrderBook(product_id = [self.product_id])
		self.init_orderbook()
		
		self.min_amount, self.quote_increment, self.min_market_funds = self.get_product_info()
		self.last_buy_price = None

		self.short_max_profit = 1.03
		self.long_max_profit = 1.06
		self.max_loss = .97
		self.max_slippage = .002

		self.equivalent_fiat = None

		self.long_flag = False
		self.short_flag = False

		self.open_orders = []
		self.order_thread = None
		self.pending_order = False
		self.order_exp = 10 #sec Time until bot should cancel limit order and create new one
		self.get_orders()

	def init_orderbook(self):
		self.orderbook.start()
		ready = False
		while not ready:
			try:
				print self.orderbook.get_ask()
				ready = True
				print "ORDERBOOK INITIALIZED"
			except:
				time.sleep(1)

	def get_product_info(self):
		ret = self.pc.get_products()
		min_amount = 0
		product_id_list = self.product_id.split("-")

		for product in ret: 
			if "{}/{}".format(product_id_list[0],product_id_list[1]) == product.get('display_name'):
				min_amount = product.get("base_min_size")
				quote_increment = product.get("quote_increment")
				min_market_funds = product.get("min_market_funds")
		return Decimal(min_amount), Decimal(quote_increment), Decimal(min_market_funds)


	def check_order(self,order_id):
		if order_id: 
			ret = self.auth_client.get_order(order_id)
			return ret

	def get_orders(self):
		order_generator = self.auth_client.get_orders()
		orders = list(order_generator)
		return orders

	def stop_limit(self,buy_price,current_price,coin_balance):
		if buy_price and coin_balance > self.min_amount: 
			if self.short_flag:
				if current_price > (buy_price*self.short_max_profit) or current_price < (buy_price*self.max_loss):
					ret = self.place_sell(current_price,coin_balance)
					
					if ret: 
						self.long_flag = False
						self.short_flag = False 
					print ret

			elif self.long_flag:
				if current_price > (buy_price*self.short_max_profit) or current_price < (buy_price*self.max_loss):
					ret = self.place_sell(current_price,coin_balance)
					
					if ret: 
						self.long_flag = False
						self.short_flag = False 
					print ret

	def round_fiat(self, money):
		return Decimal(money).quantize(Decimal('.01'), rounding=ROUND_DOWN)

	def round_coin(self, money):
		return Decimal(money).quantize(Decimal('.00000001'), rounding=ROUND_DOWN)


	def get_balances(self,pending_flag = True):
		accounts = self.auth_client.get_accounts()
		for account in accounts: 
			if account.get('currency') == 'USD':
				fiat_balance = self.round_fiat(account.get('balance'))
			if account.get('currency') == self.coin_id:
				coin_balance = self.round_coin(account.get('balance'))
		
		if pending_flag:
			pending_order_sum = Decimal(0.00)
			pending_sell_sum = Decimal(0.00000000)
			orders = self.get_orders()
			for order in orders: 
				if order.get('side') == 'buy':
					coin_size = Decimal(order.get('size'))
					price = Decimal(order.get('price'))
					pending_order_sum += self.round_fiat(coin_size * price)
				
				if order.get('side') == 'sell':
					coin_size = Decimal(order.get('size'))
					pending_sell_sum += coin_size

			fiat_balance = fiat_balance - pending_order_sum
			coin_balance = coin_balance - pending_sell_sum
		
		return coin_balance,fiat_balance	


	def get_equivalent_fiat(self):
		coin_balance,fiat_balance = self.get_balances()
		if self.equivalent_fiat is None: 
			self.run()
		return self.round_fiat(self.equivalent_fiat), coin_balance

	def get_ask(self):
		try:
			buy_price = self.orderbook.get_ask()
			return Decimal(buy_price)
		except:
			self.orderbook.close()
			time.sleep(1)
			self.init_orderbook()
			buy_price = self.orderbook.get_ask()
			return Decimal(buy_price)

	def get_bid(self):
		try:
			sell_price = self.orderbook.get_bid()
			return Decimal(sell_price)
		except:
			self.orderbook.close()
			time.sleep(1)
			self.init_orderbook()
			sell_price = self.orderbook.get_ask()
			return Decimal(sell_price)

	def buy(self,price = None,size = None,buy_type = 'limit',partial = 1.0):
		if size < self.min_amount:
			return {'status':'done'}

		if buy_type is 'limit' and price and size:
			amount = self.round_coin(size * Decimal(partial))
			if amount > self.min_amount:
				size = amount
			ret = self.auth_client.buy(price= str(price), size=str(size), product_id=self.product_id, post_only = True, order_type = "limit")

		else:
			ret = self.auth_client.buy(funds= str(self.get_balances()[1]), product_id=self.product_id, order_type = "market")

		return ret

	def place_buy(self):
		coin_balance,fiat_balance = self.get_balances()
		order_flag = False

		try: 
			auth_ret = self.auth_client.cancel_all(product_id=self.product_id)
			initial_price = self.get_ask() - self.quote_increment
			size = self.round_coin(fiat_balance/initial_price)
			if size >= self.min_amount:
				order_flag = True
				buy_price = initial_price
				self.pending_order = True
				print "Starting Buy Thread"
				while getattr(self.order_thread,"run", True) and self.buy_flag and size > self.min_amount or len(self.open_orders) > 0:
					
					#Check for max slippage and if so do a market buy
					if (1 - buy_price/initial_price) >= self.max_slippage:
						self.auth_client.cancel_all(product_id=self.product_id)
						self.buy(buy_type = 'market')
						self.pending_order = False
						return True

					if len(self.open_orders) > 0: 
						ret = self.buy(price = buy_price,size = size,buy_type = "limit",partial = 1.0)
					else: 
						ret = self.buy(price = buy_price,size = size,buy_type = "limit",partial = .5)
					
	               	#Check each order for completion or expiration of 60+ sec
					self.open_orders = self.get_orders()
					for order in self.open_orders:
						order_time = dateutil.parser.parse(order.get('created_at'))
						dt = datetime.datetime.utcnow().replace(tzinfo = tzutc()) - order_time
						if dt.total_seconds() > 60: 
							self.auth_client.cancel_order(order.get('id'))

					time.sleep(2)

					buy_price = self.get_ask() - self.quote_increment
					coin_balance,fiat_balance = self.get_balances()
					size = self.round_coin(fiat_balance/buy_price)

		except Exception as err: 
			print "Error in place_buy: {}".format(err)
	       	#Check each order for completion or expiration of 10+ sec
		auth_ret = self.auth_client.cancel_all(product_id=self.product_id)
		self.open_orders = self.get_orders()
		self.pending_order = False
		print "Exiting Buy Thread"
		return order_flag

	def sell(self,price = None,size = None,sell_type = 'limit',partial = 1.0):
		if size < self.min_amount:
			return {'status':'done'}

		if sell_type is 'limit' and price and size:
			amount = self.round_coin(size * Decimal(partial))
			if amount > self.min_amount:
				size = amount
			ret = self.auth_client.sell(price= str(price), size=str(size), product_id=self.product_id, post_only = True, order_type = "limit")

		elif sell_type == 'market':
			ret = self.auth_client.sell(size= size, product_id=self.product_id, order_type = "market")
		return ret

	def place_sell(self):
		coin_balance,fiat_balance = self.get_balances()
		order_flag = False

		try: 
			auth_ret = self.auth_client.cancel_all(product_id=self.product_id)
			initial_price = self.get_bid() + self.quote_increment
			size = coin_balance
			if size >= self.min_amount:
				order_flag = True
				sell_price = initial_price
				self.pending_order = True
				print "Starting Sell Thread"
				while getattr(self.order_thread,"run", True) and self.sell_flag and size > self.min_amount or len(self.open_orders) > 0:
					
					#Check for max slippage and if so do a market buy
					if (1 - sell_price/initial_price) >= self.max_slippage:
						self.auth_client.cancel_all(product_id=self.product_id)
						self.sell(size = size,sell_type = 'market')
						self.pending_order = False
						return True

					if len(self.open_orders) > 0: 
						ret = self.sell(price = sell_price,size = size,sell_type = "limit",partial = 1.0)
					else: 
						ret = self.sell(price = sell_price,size = size,sell_type = "limit",partial = .5)
					
	               	#Check each order for completion or expiration of 60+ sec
					self.open_orders = self.get_orders()
					for order in self.open_orders:
						order_time = dateutil.parser.parse(order.get('created_at'))
						dt = datetime.datetime.utcnow().replace(tzinfo = tzutc()) - order_time
						if dt.total_seconds() > 60: 
							self.auth_client.cancel_order(order.get('id'))

					time.sleep(2)

					sell_price = self.get_bid() + self.quote_increment
					coin_balance,fiat_balance = self.get_balances()
					size = coin_balance

		except Exception as err: 
			print "Error in place_sell: {}".format(err)
	       	#Check each order for completion or expiration of 10+ sec

		auth_ret = self.auth_client.cancel_all(product_id=self.product_id)
		self.pending_order = False
		self.open_orders = self.get_orders()
		print "Exiting Sell Thread"
		return order_flag

	def calc_fiat_balance(self,price,coin_balance,fiat_balance):
		fiat_balance = fiat_balance
		coin_value = self.round_fiat(coin_balance*price)
		equiv_balance = coin_value

		open_orders = self.auth_client.get_orders()
		if list(open_orders):
			return 

		self.equivalent_fiat = equiv_balance

	def get_price(self):
		try:
			price = self.pc.get_product_ticker(product_id = self.product_id).get('price')
			if price is None: 
				time.sleep(2)
				price = self.pc.get_product_ticker(product_id = self.product_id).get('price')
				
			return Decimal(self.pc.get_product_ticker(product_id = self.product_id).get('price'))
		except Exception as err: 
			print "ERROR IN GET_PRICE:{}".format(err)
			return Decimal(0.00)

	def run(self,short_sell_flag = False,short_buy_flag = False,long_buy_flag = False,long_sell_flag = False):
		fiat_balance = 0.00	
		coin_balance = 0.00
		try:
			price = self.get_price()
			
			self.buy_flag = False	#Lets api know that buy occured
			self.sell_flag = False	#Lets api know that sell occured
			
			#self.stop_limit(self.last_buy_price,price,coin_balance)

			#SHORT TERM LOGIC DECISIONS
			if short_buy_flag and not self.long_flag:
				print "SHORT BUY"
				if self.pending_order:
					self.order_thread.run = False
					time.sleep(2)

				self.buy_flag = True
				self.short_flag = True
				self.order_thread = threading.Thread(target=self.place_buy, name='short_buy_thread')
				self.order_thread.daemon = True
				self.order_thread.start()
				print "after thread running"


			if short_sell_flag and not self.long_flag:
				print "SHORT SELL"
				if self.pending_order:
					self.order_thread.run = False
					#wait for pending order to finish
					time.sleep(2)
				self.short_flag = False
				self.sell_flag = True
				self.order_thread = threading.Thread(target=self.place_sell, name='short_sell_thread')
				self.order_thread.daemon = True
				self.order_thread.start()
			

			#LONG TERM UPTREND LOGIC DECISIONS
			if long_buy_flag and not self.short_flag:
				print "LONG BUY"
				if self.pending_order:
					self.order_thread.run = False
					#wait for pending order to finish
					time.sleep(2)
				self.long_flag = True
				self.buy_flag = True
				self.order_thread = threading.Thread(target=self.buy, name='long_buy_thread')
				self.order_thread.daemon = True
				self.order_thread.start()
				


			if long_sell_flag and not self.short_flag: 
				print "LONG SELL"
				if self.pending_order:
					self.order_thread.run = False
					#wait for pending order to finish
					time.sleep(2)
				self.long_flag = False
				self.sell_flag = True	
				self.order_thread = threading.Thread(target=self.sell, name='long_sell_thread')
				self.order_thread.daemon = True
				self.order_thread.start()
				


			coin_balance,fiat_balance = self.get_balances()
			self.calc_fiat_balance(price,coin_balance,fiat_balance)
			print "COIN_ID: {} EQUIV_FIAT: {} COIN_BALANCE: {} FIAT_BALANCE: {}".format(self.coin_id,self.equivalent_fiat,coin_balance,fiat_balance)

			return self.equivalent_fiat,fiat_balance,coin_balance,price,self.buy_flag,self.sell_flag
		except Exception as err: 
			print err
			return self.equivalent_fiat,fiat_balance,coin_balance,price,self.buy_flag,self.sell_flag


if __name__ == '__main__':
	coin_id = "LTC"
	product_id = "LTC-USD"
	bot = gdax_bot(coin_id,product_id)
	bot.run()