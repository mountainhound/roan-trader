import requests
import roan_settings as settings

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