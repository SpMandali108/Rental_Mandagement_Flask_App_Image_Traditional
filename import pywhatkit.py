import pywhatkit

# Replace with your own phone number and current time +1 minute
phone_no = "+919327095930"
hour = 18  # 24-hour format
minute = 29 # one or two minutes ahead of current time

pywhatkit.sendwhatmsg(phone_no, "Hello from pywhatkit test!", hour, minute)