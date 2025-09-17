from pymongo import MongoClient
from collections import defaultdict
import os
from dotenv import load_dotenv

# Load env variables
load_dotenv()

# 🔹 Connect to MongoDB (use your real connection string)
mongoUrl = os.environ.get("client")
client = MongoClient(mongoUrl, tls=True, tlsAllowInvalidCertificates=True)

db = client['Image_Traditional']
collection = db['Form']

def find_conflicts():
    booking_map = defaultdict(list)  # (date, product) -> [(name, mobile)]

    for cust in collection.find({}):
        name = cust.get("Name")
        mobile = cust.get("mobile")
        bookings = cust.get("bookings", {})

        for date, products in bookings.items():
            for prod in products:
                booking_map[(date, prod)].append((name, mobile))

    conflicts = []
    for (date, prod), customers in booking_map.items():
        if len(customers) > 1:  # conflict found
            for (name, mobile) in customers:
                conflicts.append({
                    "date": date,
                    "product": prod,
                    "Name": name,
                    "mobile": mobile
                })

    return conflicts


if __name__ == "__main__":
    conflicts = find_conflicts()

    if conflicts:
        print("\nConflicting bookings found:\n")
        for c in conflicts:
            print(f"Date: {c['date']} | Product: {c['product']} | "
                  f"Name: {c['Name']} | Mobile: {c['mobile']}")
    else:
        print("\nNo conflicts found!\n")
