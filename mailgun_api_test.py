import requests
import roan_settings as settings


def check_message1(message_id):
	ret =  requests.get(
		"https://api.mailgun.net/v3/sandbox03737074c60b4a589da7ba6ddfd87a62.mailgun.org/events",
		auth=("api", "key-aca3c3c7f69f7f015a8a9d4e8e9208dd"),
		params={"message-id": message_id})
	data =  ret.json()

	for event in  data.get('items'):
		if event.get('delivery-status'):
			if event.get('delivery-status').get('attempt-no') > 1: 
				print event.get('delivery-status').get('attempt-no')
				return False

	return True

def check_message(message_id):
	ret =  requests.get(
		"{}/events".format(settings.MAILGUN_API_URL),
		auth=("api", settings.MAILGUN_API_KEY),
		params={"message-id": message_id})
	#Check if return was valid if not then do not place trade
	print "mailgon status code: {}".format(ret.status_code)
	if ret.status_code == 200:
		data =  ret.json()

		for event in  data.get('items'):
			if event.get('delivery-status'):
				if event.get('delivery-status').get('attempt-no') > 1:
					print event.get('delivery-status').get('attempt-no')
					return False
		return True

	return False

message_id = '<01010162b83da037-bb70face-5cce-4711-9f4a-cf42cf5cdc1b-000000@us-west-2.amazonses.com>'
message_id = message_id.replace('<','').replace('>','')
#message_id = message_id.replace('<','').replace('>','')
ret =  check_message(message_id)

print ret