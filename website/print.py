import os
from pymongo import MongoClient
from dotenv import load_dotenv

def print_customer_list():
    """
    Fetches all customers from the 'Form' collection and prints
    their name and mobile number to the console.
    """
    
    # 1. Load environment variables (like your DB password)
    load_dotenv()
    
    # 2. Connect to the database (copied from your auth.py)
    try:
        mongoUrl = os.environ.get("client")
        client = MongoClient(mongoUrl, tls=True, tlsAllowInvalidCertificates=True)
        db = client['Image_Traditional']
        collection = db['Form']
        
        # Test the connection
        client.admin.command('ping') 
        print("✅ Database connection successful.")
        
    except Exception as e:
        print(f"❌ ERROR: Could not connect to database.")
        print(f"Details: {e}")
        return # Stop the function if connection fails

    
    # 3. Fetch and print the data
    print("\n--- START: Customer and Mobile List ---")
    try:
        all_customers = collection.find({})
        customer_count = 0
        
        for customer in all_customers:
            name = customer.get("Name", "N/A (No Name Found)")
            mobile = customer.get("mobile", "N/A (No Mobile Found)")
            
            print(f"{name}")
            print(f"{mobile}")
            print("-------------------------")
            
            customer_count += 1
            
        print(f"--- END: Total Customers Found: {customer_count} ---\n")

    except Exception as e:
        print(f"An error occurred while trying to fetch data: {e}")
    
    finally:
        # 4. Close the database connection
        client.close()
        print("Database connection closed.")


# --- This line makes the script run when you call it from the terminal ---
if __name__ == "__main__":
    print_customer_list()