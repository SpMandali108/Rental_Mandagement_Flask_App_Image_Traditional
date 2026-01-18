from pymongo import MongoClient
import os
from dotenv import load_dotenv

load_dotenv()

mongoUrl = os.environ.get("client")
client = MongoClient(mongoUrl, tls=True, tlsAllowInvalidCertificates=True)

db = client["Image_Traditional"]

# 👉 CHANGE THIS to your target collection
collection = db["Fancy_2025_2026"]

result = collection.update_many(
    {"returned": True},          # condition
    {"$set": {"taken": True}}    # action
)

print(f"Matched documents: {result.matched_count}")
print(f"Updated documents: {result.modified_count}")
