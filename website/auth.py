import csv
import io
from flask import Response
from flask import Blueprint, render_template, request, session, redirect, url_for, flash, Response
from pymongo import MongoClient
from datetime import datetime, timedelta
from dotenv import load_dotenv
import os,csv
from fpdf import FPDF
import io
import qrcode
from flask import send_file
import io
from flask import send_file
import json
from flask import send_from_directory
from bson.objectid import ObjectId
import re
from werkzeug.utils import secure_filename
 # Find correct static image
from flask import current_app
auth = Blueprint('auth', __name__)

load_dotenv()



mongoUrl = os.environ.get("client")
client = MongoClient(mongoUrl, tls=True, tlsAllowInvalidCertificates=True)
db = client['Image_Traditional']
collection = db['Form']
fancy_2024_2025 = db['Fancy']
fancy_collection = db['Fancy_2025_2026']
products_collection = db['products']
bags = db['bags']
products = db['Storage']
fcustomers = db['Fancy_Customers']

ADMIN_ID = os.environ.get("ADMIN_ID")
ADMIN_PASS = os.environ.get("ADMIN_PASS")

def check_booking_conflict(date, products, exclude_mobile=None):
    """Check if products are already booked on given date"""
    conflicts = []
    
    for product in products:
        query = {f"bookings.{date}": {"$elemMatch": {"$eq": product}}}
        
        if exclude_mobile:
            query["mobile"] = {"$ne": exclude_mobile}
        
        existing_booking = collection.find_one(query)
        
        if existing_booking:
            conflicts.append({
                'product': product,
                'date': date,
                'customer_name': existing_booking.get('Name', 'Unknown'),
                'customer_mobile': existing_booking.get('mobile', 'Unknown')
            })
    
    return len(conflicts) > 0, conflicts



@auth.route('/admin')
def admin():
    if not session.get('logged_in'):
        return redirect(url_for('auth.login'))
    return render_template("admin.html")


@auth.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        entered_id = request.form.get('id')
        entered_pass = request.form.get('password')

        if entered_id == ADMIN_ID and entered_pass == ADMIN_PASS:
            session['logged_in'] = True
            flash("✅ Login successful!", "success")
            return redirect(url_for('auth.book'))
        else:
            flash("❌ Invalid credentials!", "error")
            return render_template('login.html')
    return render_template('login.html')

@auth.route('/main')
def main():
    if not session.get('logged_in'):
        return redirect(url_for('auth.login'))
    return render_template('main.html')

@auth.route('/logout')
def logout():
    session.pop('logged_in', None)
    flash("🔒 You have been logged out.", "info")
    return redirect(url_for('auth.login'))

@auth.route('/book', methods=['GET', 'POST'])
def book():
    if not session.get('logged_in'):
        return redirect(url_for('auth.login'))

    if request.method == 'POST':
        Name = request.form.get('name')
        mobile = request.form.get('mobile')
        given_price = request.form.get('given_price')
        price = request.form.get('price')
        address = request.form.get('address')
        deposit = request.form.get('deposit')
        group = request.form.get('group')
        reference = request.form.get('reference')

        dates = request.form.getlist('date')
        products_inputs = request.form.getlist('product')

        # Convert prices safely
        try:
            given_price_val = int(given_price) if given_price else 0
        except:
            given_price_val = 0
        try:
            total_price = int(price) if price else 0
        except:
            total_price = 0

        # Normalize dates and create bookings data
        bookings_data = []
        for date, prod_str in zip(dates, products_inputs):
            prod_list = [p.strip() for p in prod_str.split(',') if p.strip()]
            try:
                formatted_date = datetime.strptime(date, "%Y-%m-%d").strftime("%d-%m-%y")
            except:
                formatted_date = date
            bookings_data.append({"date": formatted_date, "products": prod_list})

        # -------------------- Conflict check --------------------
        for booking in bookings_data:
            date = booking['date']
            has_conflict, conflicts = check_booking_conflict(date, booking['products'])

            if has_conflict:
                conflict_msg = f"❌ Booking Failed! These products are already booked on {date}:\n"
                for conflict in conflicts:
                    conflict_msg += f"• '{conflict['product']}' by {conflict['customer_name']} ({conflict['customer_mobile']})\n"
                flash(conflict_msg, "error")
                return redirect(url_for('auth.book'))

        # -------------------- Insert / Update customer --------------------
        customer = collection.find_one({"mobile": mobile})

        if customer:
            # Existing customer → merge bookings
            bookings = customer.get('bookings', {})
            for booking_item in bookings_data:
                date = booking_item['date']
                new_prods = booking_item['products']
                if date in bookings:
                    bookings[date] = list(set(bookings[date] + new_prods))
                else:
                    bookings[date] = new_prods

            updated_total = customer.get('total_price', 0) + total_price
            updated_given = customer.get('given_price', 0) + given_price_val

            collection.update_one(
                {"_id": customer['_id']},
                {"$set": {
                    "bookings": bookings,
                    "total_price": updated_total,
                    "given_price": updated_given,
                }}
            )
        else:
            # New customer
            bookings = {b['date']: b['products'] for b in bookings_data}
            new_customer = {
                "Name": Name,
                "mobile": mobile,
                "address": address,
                "deposit": deposit,
                "group": group,
                "reference": reference,
                "bookings": bookings,
                "given_price": given_price_val,
                "total_price": total_price
            }
            collection.insert_one(new_customer)

        # -------------------- Generate QR URL --------------------
        store_base_url = "https://image-traditional.onrender.com/download-bill"
        qr_url = f"{store_base_url}?mobile={mobile}"

        collection.update_one(
            {"mobile": mobile},
            {"$set": {"qr_url": qr_url}}
        )

        flash("✅ Booking successful!", "success")
        return redirect(url_for('auth.QR', mobile=mobile))

    return render_template("book.html")



from datetime import datetime

@auth.route('/modify', methods=['GET', 'POST'])
def modify():
    if not session.get('logged_in'):
        return redirect(url_for('auth.login'))

    if request.method == 'POST':
        mobile = request.form.get('mobile')
        date_input = request.form.get('date')  # from <input type="date"> (YYYY-MM-DD)
        old_products_str = request.form.get('old_products')
        new_products_str = request.form.get('new_products')
        price_diff_str = request.form.get('price_diff')

        # Convert date → DD-MM-YY
        try:
            date_obj = datetime.strptime(date_input, "%Y-%m-%d")
            date = date_obj.strftime("%d-%m-%y")
        except ValueError:
            date = date_input  # fallback (in case already stored in correct format)

        customer = collection.find_one({"mobile": mobile})
        if not customer:
            flash("❌ No customer found with that mobile number.", "error")
            return redirect(url_for('auth.modify'))

        bookings = customer.get('bookings', {})
        if date not in bookings:
            flash(f"❌ No bookings exist for {date}.", "error")
            return redirect(url_for('auth.modify'))

        old_products = [p.strip() for p in old_products_str.split(',')] if old_products_str else []
        new_products = [p.strip() for p in new_products_str.split(',')] if new_products_str else []

        if not old_products:
            flash("❌ Please specify at least one existing product to replace.", "error")
            return redirect(url_for('auth.modify'))

        current = set(bookings[date])
        if not set(old_products).issubset(current):
            flash("❌ One or more products to remove aren't in the current booking.", "error")
            return redirect(url_for('auth.modify'))

        if set(old_products) == set(new_products):
            flash("❌ New products must differ from the ones being replaced.", "error")
            return redirect(url_for('auth.modify'))

        if new_products:
            has_conflict, conflicts = check_booking_conflict(date, new_products, exclude_mobile=mobile)
            if has_conflict:
                conflict_msg = f"❌ Cannot update! These products are already booked on {date}:\n"
                for conflict in conflicts:
                    conflict_msg += f"• '{conflict['product']}' by {conflict['customer_name']} ({conflict['customer_mobile']})\n"
                flash(conflict_msg, "error")
                return redirect(url_for('auth.modify'))

        # Update booking
        updated = [p for p in bookings[date] if p not in old_products]
        updated.extend(new_products)
        bookings[date] = updated

        try:
            price_diff = int(price_diff_str) if price_diff_str else 0
        except ValueError:
            flash("❌ Price difference must be a valid number.", "error")
            return redirect(url_for('auth.modify'))

        new_total_price = max(0, customer.get('total_price', 0) + price_diff)

        collection.update_one(
            {"mobile": mobile},
            {"$set": {
                "bookings": bookings,
                "total_price": new_total_price
            }}
        )

        flash(f"✅ Booking updated for {mobile} on {date}!", "success")
        return redirect(url_for('auth.modify'))

    return render_template("modify.html")

@auth.route('/pay_remaining', methods=['GET', 'POST'])
def pay_remaining():
    if not session.get('logged_in'):
        return redirect(url_for('auth.login'))

    customer = None
    mobile = request.args.get('mobile')  # case 1: GET ?mobile=xxxx

    if request.method == 'POST':  # case 2: POST form
        mobile = request.form.get('mobile')
        pay_amount = request.form.get('pay_amount')

        # Validate payment
        try:
            pay_amount_val = int(pay_amount)
            if pay_amount_val <= 0:
                flash("⚠️ Payment amount must be positive.", "error")
                return redirect(url_for('auth.pay_remaining', mobile=mobile))
        except:
            flash("⚠️ Invalid payment amount.", "error")
            return redirect(url_for('auth.pay_remaining', mobile=mobile))

        customer = collection.find_one({"mobile": mobile})
        if not customer:
            flash("⚠️ Customer not found.", "error")
            return redirect(url_for('auth.pay_remaining'))

        total_price = customer.get('total_price', 0)
        given_price = customer.get('given_price', 0)
        remaining = total_price - given_price

        if pay_amount_val > remaining:
            flash(f"❌ Payment exceeds remaining balance of {remaining}", "error")
            return redirect(url_for('auth.pay_remaining', mobile=mobile))

        # Update DB
        new_given_price = given_price + pay_amount_val
        collection.update_one(
            {"_id": customer['_id']},
            {"$set": {"given_price": new_given_price}}
        )

        # -------------------- Generate QR URL --------------------
        qr_url = url_for('auth.download_customer', mobile=mobile, _external=True)
        collection.update_one(
            {"mobile": mobile},
            {"$set": {"qr_url": qr_url}}
        )

         # Your live website store URL
        store_base_url = "https://image-traditional.onrender.com/download-bill"

        # Append mobile number as query parameter
        qr_url = f"{store_base_url}?mobile={mobile}"

        collection.update_one(
            {"mobile": mobile},
            {"$set": {"qr_url": qr_url}}
        )

        return redirect(url_for('auth.QR', mobile=mobile))

    # If GET or error → fetch customer for prefilled form
    if mobile:
        customer = collection.find_one({"mobile": mobile})

    return render_template("pay_remaining.html", customer=customer)




@auth.route('/delete', methods=['GET', 'POST'])
def delete():
    if not session.get('logged_in'):
        return redirect(url_for('auth.login'))

    if request.method == 'POST':
        mobile = request.form.get('mobile', "").strip()
        date_input = request.form.get('date', "").strip()
        product = request.form.get('product', "").strip()
        price_diff_str = request.form.get('price_diff', "").strip()

        # ✅ Validate Mobile
        if not mobile.isdigit() or len(mobile) != 10:
            flash("❌ Invalid mobile number. Please enter a 10-digit number.", "error")
            return redirect(url_for('auth.delete'))

        # ✅ Convert Date Format (YYYY-MM-DD → DD-MM-YY)
        try:
            date_obj = datetime.strptime(date_input, "%Y-%m-%d")
            date = date_obj.strftime("%d-%m-%y")
        except ValueError:
            flash("❌ Invalid date format.", "error")
            return redirect(url_for('auth.delete'))

        # ✅ Validate Price Difference
        try:
            price_diff = int(price_diff_str)
            if price_diff <= 0:
                raise ValueError
        except ValueError:
            flash("❌ Price difference must be a positive number.", "error")
            return redirect(url_for('auth.delete'))

        # ✅ Validate Product
        if not product:
            flash("❌ Product name cannot be empty.", "error")
            return redirect(url_for('auth.delete'))

        # 🔎 Fetch Customer
        customer = collection.find_one({"mobile": mobile})
        if not customer:
            flash(f"❌ No customer found with mobile number {mobile}.", "error")
            return redirect(url_for('auth.delete'))

        bookings = customer.get('bookings', {})
        products_for_date = bookings.get(date)

        if not products_for_date:
            flash(f"❌ No bookings found for {date}.", "error")
            return redirect(url_for('auth.delete'))

        # Normalize stored product list
        if isinstance(products_for_date, str):
            products_for_date = [p.strip() for p in products_for_date.split(',')]

        if product not in products_for_date:
            flash(f"❌ Product '{product}' not found in bookings on {date}.", "error")
            return redirect(url_for('auth.delete'))

        # 🔄 Remove product
        products_for_date.remove(product)
        if products_for_date:
            bookings[date] = products_for_date
        else:
            bookings.pop(date)

        # 💰 Update Prices
        existing_price = customer.get('total_price', 0)
        new_price = max(0, existing_price - price_diff)

        collection.update_one(
            {"_id": customer['_id']},
            {"$set": {
                "bookings": bookings,
                "total_price": new_price
            }}
        )

        flash(f"✅ Product '{product}' removed from booking on {date}. Price reduced by {price_diff}.", "success")
        return redirect(url_for('auth.delete'))

    return render_template("delete.html")


@auth.route('/profile', methods=['GET', 'POST'])
def profile():
    if not session.get('logged_in'):
        return redirect(url_for('auth.login'))
    customer = None
    error = None

    # Case 1: from clickable card → GET ?mobile=xxxx
    mobile = request.args.get('mobile')

    # Case 2: from search form → POST
    if request.method == 'POST':
        mobile = request.form.get('mobile')

    if mobile:
        customer = collection.find_one({"mobile": mobile})
        if customer:
            customer['remaining'] = customer.get('total_price', 0) - customer.get('given_price', 0)
        else:
            error = "Customer not found"

    bookings = list(collection.find())
    for b in bookings:
        b['remaining'] = b.get('total_price', 0) - b.get('given_price', 0)

    return render_template("profile.html", customer=customer, error=error,bookings=bookings)

@auth.route('/check', methods=['GET', 'POST'])
def check():
    if not session.get('logged_in'):
        return redirect(url_for('auth.login'))
    
    if request.method == 'POST':
        date = request.form.get('date')  # Example: "2025-08-29"
        product = request.form.get('product').strip().replace('k', 'K').replace('c', 'C')
        
        if not date or not product:
            flash("❌ Please provide both date and product name.", "error")
            return redirect(url_for('auth.check'))
        
        # ✅ Convert YYYY-MM-DD → DD-MM-YY
        try:
            date_obj = datetime.strptime(date, "%Y-%m-%d")
            formatted_date = date_obj.strftime("%d-%m-%y")
        except ValueError:
            # If already in DD-MM-YY
            formatted_date = date

        print("DEBUG check: input =", date, " formatted =", formatted_date)

        # ✅ Pass converted date to your conflict checker
        has_conflict, conflicts = check_booking_conflict(formatted_date, [product])
        
        if has_conflict:
            conflict = conflicts[0]
            flash(f"❌ Product '{product}' is not available on {date}. "
                  f"Already booked by {conflict['customer_name']} ({conflict['customer_mobile']}).", "error")
        else:
            flash(f"✅ Good news! Product '{product}' is available on {date}.", "success")
        
        return redirect(url_for('auth.check'))
    
    return render_template("check.html")


from datetime import datetime

@auth.route('/calendar', methods=['GET', 'POST'])
def calendar():
    if not session.get('logged_in'):
        return redirect(url_for('auth.login'))

    date = None
    bookings_on_date = []

    if request.method == 'POST':
        date = request.form.get('date')  # Example: "2025-08-29"
        if date:
            try:
                # Convert YYYY-MM-DD → DD-MM-YY
                date_obj = datetime.strptime(date, "%Y-%m-%d")
                formatted_date = date_obj.strftime("%d-%m-%y")
            except ValueError:
                # If already DD-MM-YY
                formatted_date = date  

            print("DEBUG: input =", date)
            print("DEBUG: formatted =", formatted_date)

            # ✅ Use formatted_date for querying Mongo
            customers = collection.find({f"bookings.{formatted_date}": {"$exists": True}})
            
            bookings_on_date = []
            for c in customers:
                entry = {
                    "Name": c.get("Name"),
                    "mobile": c.get("mobile"),
                    "address": c.get("address", ""),
                    "deposit": c.get("deposit", "Not provided"),
                    "group": c.get("group", ""),
                    "reference": c.get("reference", ""),
                    "products": c["bookings"].get(formatted_date, []),
                    "total_price": c.get("total_price", 0),
                    "given_price": c.get("given_price", 0),
                    "remaining": c.get("total_price", 0) - c.get("given_price", 0)
                }
                bookings_on_date.append(entry)

    return render_template(
        "calendar.html",
        date=date,  # Keep original input date for display
        bookings=bookings_on_date
    )




from flask import request, jsonify

@auth.route('/fancy', methods=['GET', 'POST'])
def fancy():
    if not session.get('logged_in'):
        return redirect(url_for('auth.login'))

    if request.method == 'POST':
        data = request.get_json()

        booking_data = {
            'Name': data.get('name'),
            'Mobile': data.get('mobile'),
            'Address': data.get('address'),
            'School': data.get('school'),
            'Start_date': data.get('start_date'),
            'End_date': data.get('end_date'),
            'Price': float(data.get('price', 0)),
            'Costume': data.get('costume'),
            'Details': data.get('details'),
            'Timestamp': datetime.now()
        }

        customer_data = {
            'Name': data.get('name'),
            'Mobile': data.get('mobile'),
            'Address': data.get('address'),
            'School': data.get('school')
        }

        # ✅ FIXED – avoids duplicates
        fcustomers.update_one(
            {'Mobile': data.get('mobile')},
            {'$set': customer_data},
            upsert=True
        )

        fancy_collection.insert_one(booking_data)

        return jsonify({'status': 'success'}), 200

    return render_template('fancy.html')

    
@auth.route('/dashboard')
def dashboard_summary():
    if not session.get('logged_in'):
        return redirect(url_for('auth.login'))

    try:
        try:
            collection.find_one()
            fancy_collection.find_one()
        except NameError as e:
            return f"Error: Database collections not properly defined - {e}"
        except Exception as e:
            return f"Error: Database connection failed - {e}"

        traditional_data = list(collection.find())

        if not traditional_data:
            total_customers_trad = 0
            total_collection_trad = 0
            total_given_trad = 0
            total_rem_trad = 0
            best_c = "N/A"
            best_c_count = 0
            best_k = "N/A"
            best_k_count = 0
            highest_booking_person = "N/A"
            highest_booking_value = 0
            avg_trad = 0
        else:
            def safe_int(val):
                try:
                    return int(val)
                except (ValueError, TypeError):
                    return 0

            total_customers_trad = len(traditional_data)
            total_collection_trad = sum(safe_int(b.get('total_price')) for b in traditional_data) + 29500
            total_given_trad = sum(safe_int(b.get('given_price')) for b in traditional_data)
            total_rem_trad = total_collection_trad - total_given_trad - 29500

            best_c, best_c_count, best_k, best_k_count = find_best_products_by_letter(traditional_data)
            highest_booking_person, highest_booking_value = find_highest_booking_customer(traditional_data)
            avg_trad = total_collection_trad / total_customers_trad if total_customers_trad > 0 else 0

        fancy_data = list(fancy_collection.find())

        if not fancy_data:
            total_customers_fancy = 0
            total_collection_fancy = 0
            avg_fancy = 0
        else:
            total_customers_fancy = len(fancy_data)
            total_collection_fancy = sum(
                int(b.get('price') or 0) for b in fancy_data if isinstance(b.get('price'), (int, float, str))
            )
            avg_fancy = total_collection_fancy / total_customers_fancy if total_customers_fancy > 0 else 0

        combined_collection = total_collection_trad + total_collection_fancy

        return render_template(
            'total.html',
            total_customers_trad=total_customers_trad,
            total_collection_trad=total_collection_trad,
            total_given_trad=total_given_trad,
            total_rem_trad=total_rem_trad,
            best_c=best_c,
            best_c_count=best_c_count,
            best_k=best_k,
            best_k_count=best_k_count,
            highest_booking_person=highest_booking_person,
            highest_booking_value=highest_booking_value,
            avg_trad=avg_trad,
            total_customers_fancy=total_customers_fancy,
            total_collection_fancy=total_collection_fancy,
            avg_fancy=avg_fancy,
            combined_collection=combined_collection
        )

    except Exception as e:
        import traceback
        traceback.print_exc()

        return render_template(
            'total.html',
            total_customers_trad=0,
            total_collection_trad=0,
            total_given_trad=0,
            total_rem_trad=0,
            best_c="Error",
            best_c_count=0,
            best_k="Error",
            best_k_count=0,
            highest_booking_person="Error",
            highest_booking_value=0,
            avg_trad=0,
            total_customers_fancy=0,
            total_collection_fancy=0,
            avg_fancy=0,
            combined_collection=0,
            has_error=True,
            error_message=str(e)
        )


def find_best_products_by_letter(traditional_data):
    product_c_counts = {}
    product_k_counts = {}

    for booking in traditional_data:
        bookings_dict = booking.get('bookings', {})
        if not isinstance(bookings_dict, dict):
            continue

        for _, products in bookings_dict.items():
            if isinstance(products, list):
                for product in products:
                    if isinstance(product, str) and product.strip():
                        product_upper = product.upper().strip()
                        if product_upper.startswith('C'):
                            product_c_counts[product_upper] = product_c_counts.get(product_upper, 0) + 1
                        elif product_upper.startswith('K'):
                            product_k_counts[product_upper] = product_k_counts.get(product_upper, 0) + 1

    if product_c_counts:
        best_c = max(product_c_counts, key=product_c_counts.get)
        best_c_count = product_c_counts[best_c]
    else:
        best_c, best_c_count = "N/A", 0

    if product_k_counts:
        best_k = max(product_k_counts, key=product_k_counts.get)
        best_k_count = product_k_counts[best_k]
    else:
        best_k, best_k_count = "N/A", 0

    return best_c, best_c_count, best_k, best_k_count


def find_highest_booking_customer(traditional_data):
    customer_totals = {}

    for booking in traditional_data:
        customer_name = booking.get('Name') or booking.get('name', 'Unknown')
        if not customer_name or customer_name.strip() in ['Unknown', '']:
            continue
        try:
            total_price = int(booking.get('total_price') or 0)
        except (ValueError, TypeError):
            total_price = 0
        customer_totals[customer_name] = customer_totals.get(customer_name, 0) + total_price

    if not customer_totals:
        return "N/A", 0

    highest_customer = max(customer_totals, key=customer_totals.get)
    highest_value = customer_totals[highest_customer]
    return highest_customer, highest_value

@auth.route('/download-customer', methods=['POST'])
def download_customer():
    mobile = request.form.get('mobile')
    if not mobile:
        return "No mobile number provided", 400

    customer = collection.find_one({"mobile": mobile})
    if not customer:
        return "Customer not found", 404

    # Remaining price
    customer['remaining'] = customer.get('total_price', 0) - customer.get('given_price', 0)

    class PDF(FPDF):
        def header(self):
            logo_path = os.path.join(os.path.dirname(__file__), "static", "favicon.png")
            if os.path.exists(logo_path):
                self.image(logo_path, 13, 5, 15)

            self.set_font('times', 'B', 20)
            self.set_x(30)
            self.cell(0, 10, 'Image Traditional', ln=1)

            self.set_x(15)
            self.set_font('helvetica', '', 10)
            self.multi_cell(
                0, 5,
                "Nr. Laxminarayan Bus-stand, Opp Prarabdh Soc.\n"
                "Maninagar(E), A'bad-08",
                align='L'
            )

            self.set_font('helvetica', 'B', 10)
            self.set_y(12)
            self.cell(0, 5, "Prakash Mandali: 9428610384", align='R')

            self.ln(20)
            y = self.get_y()
            self.line(15, y, 200, y)
            self.ln(5)

        def footer(self):
            self.set_y(-15)
            self.set_font('helvetica', 'I', 10)
            self.cell(0, 10, f'Page {self.page_no()}/{{nb}}', align='C')

    pdf = PDF('P', 'mm', 'A4')
    pdf.alias_nb_pages()
    pdf.add_page()
    pdf.set_font('times', 'B', 11)

    # ------- Customer Details -------
    def add_field(label, value):
        pdf.set_x(15)
        text = f"{label}: {value}"
        pdf.cell(pdf.get_string_width(text)+4, 8, text, border=1)
        pdf.ln(10)

    add_field("Name", customer.get("Name", "N/A"))
    add_field("Mobile", customer.get("mobile", "N/A"))
    add_field("Address", customer.get("address", "N/A"))
    add_field("Group", customer.get("group", "N/A"))
    add_field("Reference", customer.get("reference", "N/A"))
    add_field("Deposit", customer.get("deposit", "N/A"))

    pdf.ln(3)

    # ------- Table Header -------
    pdf.set_font("helvetica", "B", 10)
    pdf.set_x(15)
    pdf.cell(10, 10, "Sr", border=1, align="C")
    pdf.cell(40, 10, "Product Code", border=1, align="C")
    pdf.cell(40, 10, "Image", border=1, align="C")
    pdf.cell(40, 10, "Date", border=1, align="C")
    pdf.ln()

    pdf.set_font("helvetica", "", 10)

    # ------- Fill Table with Bookings -------
    sr = 1
    bookings = customer.get("bookings", {})

    for date, codes in bookings.items():
        for code in codes:
            pdf.set_x(15)
            pdf.cell(10, 25, str(sr), border=1, align="C")
            pdf.cell(40, 25, code, border=1, align="C")

            # Reserve image cell
            x = pdf.get_x()
            y = pdf.get_y()
            pdf.cell(40, 25, "", border=1)

           

            if code.startswith("K"):
                img_path = os.path.join(current_app.static_folder, "KediyaJpg", f"{code}.jpg")
            elif code.startswith("C"):
                img_path = os.path.join(current_app.static_folder, "CholiJpg", f"{code}.jpg")
            elif code.startswith("G"):
                img_path = os.path.join(current_app.static_folder, "GroupJpg", f"{code}.jpg")


            if img_path and os.path.exists(img_path):
                pdf.image(img_path, x+2, y+2, 36, 21)  # fit in cell

            pdf.cell(40, 25, date, border=1, align="C")
            pdf.ln()

            sr += 1

    # ------- Prices -------
    pdf.ln(5)
    add_field("Total Price", customer.get("total_price", 0))
    add_field("Given Price", customer.get("given_price", 0))
    add_field("Remaining", customer["remaining"])

    # Output PDF
    # Replace the PDF output section at the end of your function with this:

    # Output PDF - CORRECTED VERSION
    # Output PDF as bytes
    pdf_output = pdf.output(dest="S")

# If it's str, encode; if it's already bytes/bytearray, just wrap
    if isinstance(pdf_output, str):
        pdf_bytes = pdf_output.encode("latin1")
    else:
        pdf_bytes = bytes(pdf_output)   # handles bytearray or bytes

    pdf_buffer = io.BytesIO(pdf_bytes)
    pdf_buffer.seek(0)

    filename = f"{customer.get('Name', 'customer')}_Profile.pdf"

    return send_file(
        pdf_buffer,
        as_attachment=True,
        download_name=filename,
        mimetype="application/pdf"
    )





@auth.route("/choli")
def choli():
    with open('choli.json') as f:
        products = json.load(f)
    return render_template("choli.html", products=products)

@auth.route("/kediya")
def kediya():
    with open('kediya.json') as f:
        products = json.load(f)
    return render_template("kediya.html", products=products)

@auth.route("/sitemap.xml")
def sitemap():
    return send_from_directory('static', 'sitemap.xml', mimetype='application/xml')


@auth.route('/robots.txt')
def robots():
    return "Sitemap: https://image-traditional.onrender.com/sitemap.xml", 200, {'Content-Type': 'text/plain'}

@auth.route('/search', methods=['GET', 'POST'])
def search():
    query = None
    normal_results = []
    fancy_results = []

    if not session.get('logged_in'):
        return redirect(url_for('auth.login'))

    if request.method == 'POST':
        query = request.form.get('search')

        # --------------------------
        # Normal Collection Search
        # --------------------------
        normal_matches = collection.find({
            "$or": [
                {"Name": {"$regex": query, "$options": "i"}},
                {"mobile": {"$regex": query, "$options": "i"}},
                {"address": {"$regex": query, "$options": "i"}},
                {"group": {"$regex": query, "$options": "i"}},
                {"reference": {"$regex": query, "$options": "i"}},
                {"bookings": {"$exists": True}}
            ]
        })

        for c in normal_matches:
            bookings = c.get("bookings", {})
            total_price = bookings.get("total_price", c.get("total_price", ""))
            given_price = bookings.get("given_price", c.get("given_price", ""))

            for date_key, products in bookings.items():
                if date_key in ["total_price", "given_price"]:
                    continue
                if isinstance(products, list):
                    for product in products:
                        if query.lower() in str(product).lower() \
                           or query.lower() in c.get("Name", "").lower() \
                           or query.lower() in c.get("mobile", "").lower() \
                           or query.lower() in c.get("address", "").lower() \
                           or query.lower() in c.get("group", "").lower() \
                           or query.lower() in c.get("reference", "").lower():
                            normal_results.append({
                                "name": c.get("Name", "N/A"),
                                "mobile": c.get("mobile", "N/A"),
                                "address": c.get("address", "N/A"),
                                "group": c.get("group", "N/A"),
                                "reference": c.get("reference", "N/A"),
                                "product_code": product,
                                "date": date_key,
                                "total_price": total_price,
                                "given_price": given_price
                            })

        # --------------------------
        # Fancy Collection Search
        # --------------------------
        fancy_matches = fancy_collection.find({
            "$or": [
                {"name": {"$regex": query, "$options": "i"}},
                {"mobile": {"$regex": query, "$options": "i"}},
                {"address": {"$regex": query, "$options": "i"}},
                {"Address": {"$regex": query, "$options": "i"}},  # handle capital A
                {"costume": {"$regex": query, "$options": "i"}},
                {"details": {"$regex": query, "$options": "i"}},
            ]
        })

        for f in fancy_matches:
            fancy_results.append({
                "name": f.get("name", "N/A"),
                "mobile": f.get("mobile", "N/A"),
                "address": f.get("address") or f.get("Address", "N/A"),
                "costume": f.get("costume", "N/A"),
                "details": f.get("details", "N/A"),
                "start_date": f.get("start_date", "N/A"),
                "end_date": f.get("end_date", "N/A"),
                "price": f.get("price", "N/A"),
            })

    return render_template("search.html", query=query,
                           normal_results=normal_results,
                           fancy_results=fancy_results)

@auth.route("/export_bookings")
def export_bookings():
    if not session.get('logged_in'):
        return redirect(url_for('auth.login'))
    docs = list(collection.find())

    # Collect all unique booking dates (keys in bookings except prices)
    date_keys = set()
    for doc in docs:
        bookings = doc.get("bookings", {})
        for key in bookings.keys():
            if key not in ("given_price", "total_price"):
                date_keys.add(key)
    date_keys = sorted(date_keys)

    # Collect all other top-level keys except '_id' and 'bookings'
    other_keys = set()
    for doc in docs:
        for key in doc.keys():
            if key not in ("_id", "bookings"):
                other_keys.add(key)
    other_keys = sorted(other_keys)

    # Prepare CSV fieldnames (other keys + booking dates)
    fieldnames = other_keys + date_keys

    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=fieldnames)
    writer.writeheader()

    for doc in docs:
        row = {}

        # Add other top-level fields
        for key in other_keys:
            value = doc.get(key, "")
            # Convert complex types to string
            if isinstance(value, (dict, list)):
                value = str(value)
            row[key] = value

        # Add booking dates with product lists
        bookings = doc.get("bookings", {})
        for date in date_keys:
            products = bookings.get(date, [])
            if isinstance(products, list):
                row[date] = ", ".join(str(p) for p in products)
            else:
                row[date] = ""

        writer.writerow(row)

    output.seek(0)
    return Response(
        output,
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment;filename=bookings_export.csv"}
    )
@auth.route("/listing",methods=['GET', 'POST'])
def listing():
    if not session.get('logged_in'):
        return redirect(url_for('auth.login'))

    bookings = list(collection.find())
    for b in bookings:
        b['remaining'] = b.get('total_price', 0) - b.get('given_price', 0)

    return render_template("listing.html", bookings=bookings)

@auth.route("/fancy_listing",methods=['GET','POST'])
def flisting():
    if not session.get('logged_in'):
        return redirect(url_for('auth.login'))
    
    fbookings = list(fancy_collection.find())

    return render_template("fancy_listing.html",fbookings = fbookings)

@auth.route("/download-bill", methods=["GET", "POST"])
def download_bill_page():
    mobile = request.args.get("mobile", "")
    return render_template("download_bill.html", mobile=mobile)

@auth.route("/generate-qr/<mobile>")
def generate_qr(mobile):
    customer = collection.find_one({"mobile": mobile})
    if not customer:
        return "Customer not found", 404

    qr_url = customer.get("qr_url")
    if not qr_url:
        return "QR URL not found", 404

    qr_img = qrcode.make(qr_url)
    buf = io.BytesIO()
    qr_img.save(buf, format="PNG")
    buf.seek(0)

    return send_file(buf, mimetype="image/png")

@auth.route("/QR/<mobile>")
def QR(mobile):
    customer = collection.find_one({"mobile": mobile})
    if not customer:
        flash("Customer not found", "warning")
        return redirect(url_for("auth.book"))

    qr_url = customer.get("qr_url")
    return render_template("QR.html", customer=customer, qr_url=qr_url)

@auth.route('/payment_success')
def payment_success():
    if not session.get('logged_in'):
        return redirect(url_for('auth.login'))

    mobile = request.args.get('mobile')
    customer = collection.find_one({"mobile": mobile}) if mobile else None

    if not customer:
        flash("⚠️ Customer not found.", "error")
        return redirect(url_for('auth.profile'))

    return render_template("payment_success.html", customer=customer)


@auth.route("/inventory")
def inventory():
    if not session.get('logged_in'):
        return redirect(url_for('auth.login'))

   
    products = []

    # Generate C1 - C150
    for i in range(1, 151):
        products.append({"code": f"C{i}"})

    # Generate K1 - K173
    for i in range(1, 174):
        products.append({"code": f"K{i}"})

    return render_template("inventory.html", products=products)

# Save product status to 'products' collection
@auth.route("/update_status", methods=["POST"])
def update_status():
    data = request.json
    product_code = data.get("product_code")
    status = data.get("status")
    if product_code and status:
        products_collection.update_one(
            {"product_code": product_code},  # if exists
            {"$set": {"status": status}},    # update status
            upsert=True                       # insert if not exists
        )
        return jsonify({"success": True})
    return jsonify({"success": False, "message": "Invalid data"}), 400

# Retrieve all product statuses
@auth.route("/get_statuses", methods=["GET"])
def get_statuses():
    statuses = products_collection.find({}, {"_id": 0})
    return jsonify({item["product_code"]: item["status"] for item in statuses})

# Clear all product statuses
@auth.route("/clear_statuses", methods=["POST"])
def clear_statuses():
    products_collection.delete_many({})
    return jsonify({"success": True})



from flask import Blueprint, render_template, current_app, url_for, abort
from pymongo import ASCENDING

@auth.route("/code/<code>")
def code_detail(code):
    if not session.get('logged_in'):
        return redirect(url_for('auth.login'))


    pipeline = [
    {"$project": {
        "Name": 1,
        "mobile": 1,
        "address": 1,
        "deposit": 1,
        "group": 1,
        "reference": 1,
        "given_price": 1,
        "total_price": 1,
        "bookingsArr": {"$objectToArray": "$bookings"}  # convert object to array
    }},
    {"$unwind": "$bookingsArr"},
    {"$match": {"bookingsArr.v": {"$in": [code]}}}, 
    {"$project": {
        "dateStr": "$bookingsArr.k",
        "day": {"$toInt": {"$substr": ["$bookingsArr.k", 0, 2]}},
        "month": {"$toInt": {"$substr": ["$bookingsArr.k", 3, 2]}},
        "year": {"$toInt": {"$concat": ["20", {"$substr": ["$bookingsArr.k", 6, 2]}]}},
        "user": {
            "Name": "$Name",
            "mobile": "$mobile",
            "address": "$address",
            "group": "$group",
            "reference": "$reference",
            "deposit": "$deposit"
        },
        "given_price": "$given_price",
        "total_price": "$total_price"
    }},
    {"$group": {
        "_id": "$dateStr",
        "year": {"$first": "$year"},
        "month": {"$first": "$month"},
        "day": {"$first": "$day"},
        "bookings": {"$push": {
            "user": "$user",
            "given_price": "$given_price",
            "total_price": "$total_price"
        }}
    }}
]



    results = list(collection.aggregate(pipeline))

# Sort in Python by year, month, day
    results.sort(key=lambda r: (r["year"], r["month"], r["day"]))

# Prepare for template
    bookings_by_date = [{"date": r["_id"], "bookings": r["bookings"]} for r in results]


    if not results:
        return render_template("no_booking.html", code=code)

    # simplify for template
    bookings_by_date = [{"date": r["_id"], "bookings": r["bookings"]} for r in results]

    # build image path (static/images/c1.jpg, k1.jpg etc.)
    if code.startswith("K"):
        image_url = url_for("static", filename=f"Kediya/{code}.webp")
    elif code.startswith("C"):
        image_url = url_for("static", filename=f"Choli/{code}.webp")
    else:
        image_url = None

    return render_template(
        "code.html",
        code=code,
        image_url=image_url,
        bookings_by_date=bookings_by_date
    )
@auth.route("/product")
def product():
    if not session.get('logged_in'):
        return redirect(url_for('auth.login'))
    # Capitalize first letter for URLs
    codes = [f"C{i}" for i in range(1, 151)] + [f"K{i}" for i in range(1, 174)]
    return render_template("product.html", codes=codes)

@auth.route("/dashboard_listing",methods=['GET', 'POST'])
def dashboard_listing():
    if not session.get('logged_in'):
        return redirect(url_for('auth.login'))

    bookings = list(collection.find())
    for b in bookings:
        b['remaining'] = b.get('total_price', 0) - b.get('given_price', 0)

    return render_template("dashboard_listing.html", bookings=bookings)

# Put these imports near top of your file if not already present
from flask import render_template, request, session, redirect, url_for
from datetime import datetime

# Add/replace this route in your blueprint (auth)
@auth.route('/available', methods=['GET', 'POST'])
def available():
    # require login (same pattern as your other routes)
    if not session.get('logged_in'):
        return redirect(url_for('auth.login'))

    date = None
    filter_val = "all"   # default filter
    remaining_c = []
    remaining_k = []

    # Generate inventory codes (no image filenames here; template builds .webp path)
    all_c = [{"code": f"C{i}"} for i in range(1, 151)]
    all_k = [{"code": f"K{i}"} for i in range(1, 174)]

    if request.method == 'POST':
        date = request.form.get('date')              # YYYY-MM-DD from form
        filter_val = request.form.get('filter', 'all')

        if date:
            # convert date to your DB key format (DD-MM-YY). fallback to raw if parse fails
            try:
                date_obj = datetime.strptime(date, "%Y-%m-%d")
                formatted_date = date_obj.strftime("%d-%m-%y")
            except Exception:
                formatted_date = date

            # Collect booked codes for that date (safe check, handles list or comma-string)
            booked = set()
            for doc in collection.find({}):
                bookings = doc.get("bookings", {})
                if not isinstance(bookings, dict):
                    continue
                if formatted_date in bookings:
                    value = bookings.get(formatted_date, [])
                    # normalize: could be list or string like "C1,C2"
                    if isinstance(value, str):
                        items = [p.strip() for p in value.split(',') if p.strip()]
                    elif isinstance(value, list):
                        items = value
                    else:
                        items = []

                    for p in items:
                        if not isinstance(p, str):
                            continue
                        booked.add(p.strip().upper())

            # Debug prints (check server console)
            print(f"[DEBUG] Booked on {formatted_date} => {len(booked)} items: {sorted(booked)[:50]}")

            # Build remaining lists (exclude booked codes)
            remaining_c = [p for p in all_c if p["code"].upper() not in booked]
            remaining_k = [p for p in all_k if p["code"].upper() not in booked]

    # Render template and pass filter to make radio sticky
    return render_template(
        "available.html",
        date=date,
        remaining_c=remaining_c,
        remaining_k=remaining_k,
        filter=filter_val
    )

@auth.route('/add_bag', methods=['POST'])
def add_bag():
    if not session.get('logged_in'):
        return redirect(url_for('auth.login'))
    name = request.form.get('name')
    desc = request.form.get('bag_description', '')
    bags.insert_one({'name': name, 'description': desc})
    return redirect(url_for('auth.Storage'))

# -----------------------
# ADD MULTIPLE PRODUCTS
# -----------------------
@auth.route('/add_product', methods=['POST'])
def add_product():
    if not session.get('logged_in'):
        return redirect(url_for('auth.login'))
    bag_id = request.form['bag_id']
    codes = request.form.getlist('product_codes')  # checkboxes
    custom_code = request.form.get('custom_code', '').strip()

    # Include custom code if provided
    if custom_code:
        codes.append(custom_code)

    for code in codes:
        code = code.strip()
        if code:
            try:
                products.insert_one({
                    "_id": code,
                    "bag_id": str(bag_id)
                })
            except Exception as e:
                print(f"Skipping duplicate code: {code}")

    return redirect(url_for('auth.Storage'))

# -----------------------
# STORAGE PAGE / SEARCH
# -----------------------
@auth.route('/Storage', methods=['GET', 'POST'])
def Storage():
    if not session.get('logged_in'):
        return redirect(url_for('auth.login'))
    result = None
    if request.method == 'POST':
        search_type = request.form['search_type']
        query = request.form['query'].strip()

        if search_type == 'product':
            result = products.find_one({"_id": query})
            if result:
                bag_id = result.get('bag_id')
                bag = bags.find_one({"_id": ObjectId(bag_id)}) if ObjectId.is_valid(bag_id) else bags.find_one({"_id": bag_id})
                if bag:
                    result['bag_name'] = bag.get('name', 'Unknown')
                    result['bag_description'] = bag.get('description', 'No description')
                else:
                    result['bag_name'] = 'Unknown'
                    result['bag_description'] = 'No description'

        elif search_type == 'bag':
            bag = bags.find_one({"name": query})
            if bag:
                bag_id_str = str(bag['_id'])
                result = list(products.find({"bag_id": bag_id_str}))
            else:
                result = []

    all_bags = list(bags.find())

    # Generate available codes (for checkboxes)
    all_codes = [f'C{i}' for i in range(1, 151)] + [f'K{i}' for i in range(1, 174)]
    used_codes = [p['_id'] for p in products.find({}, {"_id": 1})]
    available_codes = [c for c in all_codes if c not in used_codes]

    return render_template('Storage.html', result=result, bags=all_bags, available_codes=available_codes)

def get_all_product_counts():
    """
    Loops through the entire database ONCE and counts all product bookings.
    
    Returns a dictionary of all product codes and their total booking count.
    Example: {'C1': 12, 'K5': 9, 'C10': 5}
    """
    
    # 1. Initialize an empty dictionary to store the counts
    product_counts = {}
    
    # 2. Get all customers from the database
    all_customers = collection.find({})
    
    # 3. Loop through each customer
    for customer in all_customers:
        bookings_dict = customer.get("bookings", {})
        
        # Skip if bookings data is not a dictionary
        if not isinstance(bookings_dict, dict):
            continue
            
        # 4. Loop through all booking dates for that customer
        for date_key, products_data in bookings_dict.items():
            
            # Skip special keys that aren't dates
            if date_key in ["total_price", "given_price"]:
                continue
            
            # 5. Standardize the 'products' data
            # (Your DB sometimes has a list, sometimes a comma-string)
            products_list = []
            if isinstance(products_data, list):
                products_list = products_data
            elif isinstance(products_data, str):
                products_list = [p.strip() for p in products_data.split(',') if p.strip()]
            
            # 6. Loop through the products for this one booking
            for product_code in products_list:
                
                # Clean the product code
                cleaned_code = product_code.strip().upper()
                
                # Skip empty strings
                if not cleaned_code:
                    continue
                
                # 7. Increment the count for this product
                # .get(cleaned_code, 0) fetches the current count, or 0 if it's the first time
                product_counts[cleaned_code] = product_counts.get(cleaned_code, 0) + 1
                    
    return product_counts


@auth.route('/export_product_report')
def export_product_report():
    if not session.get('logged_in'):
        return redirect(url_for('auth.login'))

    # 1. Get the dictionary of all counts
    #    Example: {'C1': 12, 'K5': 9, 'C10': 5}
    try:
        all_counts = get_all_product_counts()
    except Exception as e:
        return f"Error running get_all_product_counts: {e}"

    # 2. Sort the products by count (most popular first)
    #    This converts the dict to a list of tuples: [('C1', 12), ('K5', 9), ...]
    sorted_products = sorted(all_counts.items(), key=lambda item: item[1], reverse=True)

    # 3. Create an in-memory text buffer
    output = io.StringIO()
    
    # 4. Create a CSV writer object
    writer = csv.writer(output)

    # 5. Write the Header Row
    writer.writerow(['Product_Code', 'Times_Rented'])

    # 6. Write all the data rows
    for product_code, count in sorted_products:
        writer.writerow([product_code, count])

    # 7. Go back to the start of the in-memory file
    output.seek(0)

    # 8. Send the file to the browser as a download
    return Response(
        output,
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment;filename=product_popularity_report.csv"}
    )

@auth.route("/migration", methods=['GET', 'POST'])
def migration():
    if not session.get('logged_in'):
        return redirect(url_for('auth.login'))
    
    for b in fancy_collection.find():
        mobile = b.get("mobile")
        name = b.get("name")
        address = b.get("Address")
        school = b.get("School")

        # Skip if already exists
        if fcustomers.find_one({"mobile": mobile}):
            continue

        # Insert only if mobile exists
        if mobile:
            fcustomers.insert_one({
                "mobile": mobile,
                "name": name,
                "address": address,
                "School":school
            })

    return "Migration completed!"

@auth.route("/get_customer")
def get_customer():
    mobile = request.args.get("mobile")

    customer = fcustomers.find_one(
        {"mobile": mobile},     # lowercase mobile
        {"_id": 0}
    )

    if customer:
        return jsonify({"exists": True, "data": customer})

    return jsonify({"exists": False})


import os
import re
from flask import current_app, render_template, abort
from werkzeug.utils import secure_filename


@auth.route('/catalogue/fancy/')
def catalogue():

    # Map subfolder name → icon filename
    icon_map = {
        "Bhagwan":            "bhagwan.png",
        "Mataji":             "mataji.png",
        "Profession":         "Proffesion.png",
        "Freedom Fighter":    "Freedom Fighter.png",
        "Regional":           "Regional.png",
        "Wild Animals":       "Wild_Animal.png",
        "Domestic Animals":   "Domestic_Animal.png",
        "Water Animals":      "Water_Animal.png",
        "Insects":            "Insect.png",
        "Birds":              "Bird.png",
        "Fruits":             "Fruit.png",
        "Vegetables":         "Vegetable.png",
        "Halloween":          "Halloween.png",
        "Cartoon":            "Cartoon.png",
        "Superhero":          "Superhero.png",
        "International":      "International.png",
        "Flexi":              "Flex.png",
        "Nature":             "Nature.png",
        "Tiranga":            "Tiranga.png",
        "Others":             "Other.png"    
        
    }

    subfolders = list(icon_map.keys())

    return render_template(
        'fancy_subcategories.html',
        subfolders=subfolders,
        icon_map=icon_map,
    )


@auth.route('/catalogue/fancy/<sub>/')
def fancy_sub(sub):
    sub = secure_filename(sub)
    BASE_DIR = os.path.join(current_app.root_path, 'static', 'Products')
    folder_path = os.path.join(BASE_DIR, 'Fancy', sub)

    if not os.path.exists(folder_path):
        abort(404)

    raw_images = [
        f for f in os.listdir(folder_path)
        if f.lower().endswith(('.png', '.jpg', '.jpeg', '.webp'))
    ]

    # Build list of (filename, clean_display_name) tuples
    images = []
    for f in sorted(raw_images):
        stem = os.path.splitext(f)[0]          # "bhagwan1"
        clean = re.sub(r'\d+$', '', stem)      # "bhagwan"
        clean = clean.replace('_', ' ').replace('-', ' ').strip().title()  # "Bhagwan"
        images.append({'file': f, 'name': clean})

    return render_template(
        'fancy_gallery.html',
        sub=sub,
        images=images
    )