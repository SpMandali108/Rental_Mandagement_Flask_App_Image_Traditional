from flask import Blueprint, render_template, request, session, redirect, url_for, flash
from pymongo import MongoClient
from datetime import datetime, timedelta
from dotenv import load_dotenv
import os
from fpdf import FPDF
import io
from flask import send_file
import json
auth = Blueprint('auth', __name__)

load_dotenv()

mongoUrl = os.environ.get("client")
client = MongoClient(mongoUrl, tls=True, tlsAllowInvalidCertificates=True)
db = client['Image_Traditional']
collection = db['Form']
fancy_collection = db['Fancy']

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

        try:
            given_price_val = int(given_price) if given_price else 0
        except:
            given_price_val = 0

        try:
            total_price = int(price)
        except:
            total_price = 0

        bookings_data = []
        for date, prod_str in zip(dates, products_inputs):
            prod_list = [p.strip() for p in prod_str.split(',') if p.strip()]
            bookings_data.append({"date": date, "products": prod_list})

        
        for booking in bookings_data:
            date = booking['date']
            has_conflict, conflicts = check_booking_conflict(date, booking['products'])
            
            if has_conflict:
                conflict_msg = f"❌ Booking Failed! These products are already booked on {date}:\n"
                for conflict in conflicts:
                    conflict_msg += f"• '{conflict['product']}' by {conflict['customer_name']} ({conflict['customer_mobile']})\n"
                flash(conflict_msg, "error")
                return redirect(url_for('auth.book'))

        customer = collection.find_one({"mobile": mobile})

        if customer:
            bookings = customer.get('bookings', {})
            for booking in bookings_data:
                date = booking['date']
                new_prods = booking['products']
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
                    "address": address,
                    "deposit": deposit,
                    "group": group,
                    "reference": reference,
                    "Name": Name
                }}
            )
        else:
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

       

        flash("✅ Booking successful!", "success")
        return redirect(url_for('auth.book'))

    return render_template("book.html")

@auth.route('/modify', methods=['GET', 'POST'])
def modify():
    if not session.get('logged_in'):
        return redirect(url_for('auth.login'))

    if request.method == 'POST':
        mobile = request.form.get('mobile')
        date = request.form.get('date')
        old_products_str = request.form.get('old_products')
        new_products_str = request.form.get('new_products')
        price_diff_str = request.form.get('price_diff')

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

        customer = collection.find_one({"mobile": mobile})
       
        flash(f"✅ Booking updated for {mobile} on {date}!", "success")
        return redirect(url_for('auth.modify'))

    return render_template("modify.html")

@auth.route('/pay_remaining', methods=['GET', 'POST'])
def pay_remaining():
    if not session.get('logged_in'):
        return redirect(url_for('auth.login'))

    if request.method == 'POST':
        mobile = request.form.get('mobile')
        pay_amount = request.form.get('pay_amount')

        try:
            pay_amount_val = int(pay_amount)
            if pay_amount_val <= 0:
                flash("⚠️ Payment amount must be positive.", "error")
                return redirect(url_for('auth.pay_remaining'))
        except:
            flash("⚠️ Invalid payment amount.", "error")
            return redirect(url_for('auth.pay_remaining'))

        customer = collection.find_one({"mobile": mobile})
        if not customer:
            flash("⚠️ Customer not found.", "error")
            return redirect(url_for('auth.pay_remaining'))

        total_price = customer.get('total_price', 0)
        given_price = customer.get('given_price', 0)
        remaining = total_price - given_price

        if pay_amount_val > remaining:
            flash(f"❌ Payment amount exceeds remaining balance of ₹{remaining}", "error")
            return redirect(url_for('auth.pay_remaining'))

        new_given_price = given_price + pay_amount_val
        collection.update_one({"_id": customer['_id']}, {"$set": {"given_price": new_given_price}})

       
        flash(f"✅ Payment of ₹{pay_amount_val} accepted! Remaining: ₹{total_price - new_given_price}", "success")
        return redirect(url_for('auth.pay_remaining'))

    return render_template("pay_remaining.html")

@auth.route('/delete', methods=['GET', 'POST'])
def delete():
    if not session.get('logged_in'):
        return redirect(url_for('auth.login'))

    if request.method == 'POST':
        mobile = request.form.get('mobile')
        date = request.form.get('date')
        product = request.form.get('product').strip()

        try:
            price_diff = float(request.form.get('price_diff'))
        except ValueError:
            flash("❌ Invalid price difference value.", "error")
            return redirect(url_for('auth.delete'))

        customer = collection.find_one({"mobile": mobile})
        if not customer:
            flash(f"❌ No customer found with mobile number {mobile}.", "error")
            return redirect(url_for('auth.delete'))

        bookings = customer.get('bookings', {})
        products_for_date = bookings.get(date)
        if not products_for_date:
            flash(f"❌ No bookings found for date {date}.", "error")
            return redirect(url_for('auth.delete'))

        if isinstance(products_for_date, str):
            products_for_date = [p.strip() for p in products_for_date.split(',')]

        if product not in products_for_date:
            flash(f"❌ Product '{product}' not found in bookings on {date}.", "error")
            return redirect(url_for('auth.delete'))

        products_for_date.remove(product)
        if products_for_date:
            bookings[date] = products_for_date
        else:
            bookings.pop(date)

        existing_price = customer.get('total_price', 0)
        existing_given = customer.get('given_price', 0)
        new_price = max(0, existing_price - price_diff)

        collection.update_one(
            {"_id": customer['_id']},
            {"$set": {
                "bookings": bookings,
                "total_price": new_price
            }}
        )

     

        flash(f"✅ Product '{product}' removed from booking on {date}. Price reduced by ₹{price_diff}.", "success")
        return redirect(url_for('auth.delete'))

    return render_template("delete.html")

@auth.route('/profile', methods=['GET', 'POST'])
def profile():
    

    if request.method == 'POST':
        mobile = request.form.get('mobile')
        if mobile:
            customer = collection.find_one({"mobile": mobile})
            if customer:
                customer['remaining'] = customer.get('total_price', 0) - customer.get('given_price', 0)
                return render_template("profile.html", customer=customer)
            else:
                return render_template("profile.html", error="Customer not found")
    
    return render_template("profile.html")

@auth.route('/check', methods=['GET', 'POST'])
def check():
    if not session.get('logged_in'):
        return redirect(url_for('auth.login'))
    
    if request.method == 'POST':
        date = request.form.get('date')
        product = request.form.get('product').strip().replace('k', 'K').replace('c', 'C')
        
        if not date or not product:
            flash("❌ Please provide both date and product name.", "error")
            return redirect(url_for('auth.check'))
        
        has_conflict, conflicts = check_booking_conflict(date, [product])
        
        if has_conflict:
            conflict = conflicts[0]
            flash(f"❌ Product '{product}' is not available on {date}. "
                  f"Already booked by {conflict['customer_name']} ({conflict['customer_mobile']}).", "error")
        else:
            flash(f"✅ Good news! Product '{product}' is available on {date}.", "success")
        
        return redirect(url_for('auth.check'))
    
    return render_template("check.html")

@auth.route('/calendar', methods=['GET', 'POST'])
def calendar():
    if not session.get('logged_in'):
        return redirect(url_for('auth.login'))

    date = None
    bookings_on_date = []

    if request.method == 'POST':
        date = request.form.get('date')
        if date:
            customers = collection.find({f"bookings.{date}": {"$exists": True}})
            for c in customers:
                products = c['bookings'].get(date, [])
                bookings_on_date.append({
                    "Name": c.get("Name", "Unknown"),
                    "mobile": c.get("mobile", "Unknown"),
                    "address": c.get("address", "Not provided"),
                    "deposit": c.get("deposit", "Not provided"),
                    "group": c.get("group", "Not specified"),
                    "reference": c.get("reference", ""),
                    "products": products
                })

    return render_template("calendar.html", date=date, bookings=bookings_on_date)






from flask import request, jsonify

@auth.route('/fancy', methods=['GET', 'POST'])
def fancy():
    if not session.get('logged_in'):
        return redirect(url_for('auth.login'))
    if request.method == 'POST':
        data = request.get_json()

        booking_data = {
            'name': data.get('name'),
            'mobile': data.get('mobile'),
            'Address': data.get('address'),
            'start_date': data.get('start_date'),
            'end_date': data.get('end_date'),
            'price': float(data.get('price', 0)),
            'costume': data.get('costume'),
            'details': data.get('details'),
            'timestamp': datetime.now()
        }

        fancy_collection.insert_one(booking_data)
        return jsonify({'status': 'success'}), 200

    return render_template('fancy.html')


    if request.method == 'POST':
        booking_data = {
            'name': request.form['name'],
            'mobile': request.form['mobile'],
            'Address': request.form['address'],
            'start_date': request.form['start_date'],
            'end_date': request.form['end_date'],
            'price': float(request.form['price']),
            'costume': request.form['costume'],
            'details': request.form['details'],
            'timestamp': datetime.now()
        }

        # Save to MongoDB
        fancy_collection.insert_one(booking_data)


        
      
        flash('Booking submitted successfully', 'success')
        return redirect(url_for('auth.fancy'))

    return render_template('fancy.html')
@auth.route('/dashboard')
def total():
    if not session.get('logged_in'):
        return redirect(url_for('auth.login'))


    total_bookings = collection.count_documents({})
    total_fancy_bookings = fancy_collection.count_documents({})


    total_price = sum(booking.get('total_price', 0) for booking in collection.find())
    total_fancy_price = sum(booking.get('price', 0) for booking in fancy_collection.find())


    return render_template('total.html', 
                           total_bookings=total_bookings,
                           total_fancy_bookings=total_fancy_bookings,
                           total_price=total_price,
                           total_fancy_price=total_fancy_price)

@auth.route('/download-customer', methods=['POST'])
def download_customer():
    

    mobile = request.form.get('mobile')
    if not mobile:
        return "No mobile number provided", 400

    customer = collection.find_one({"mobile": mobile})
    if not customer:
        return "Customer not found", 404

    customer['remaining'] = customer.get('total_price', 0) - customer.get('given_price', 0)

    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", size=12)

    pdf.cell(200, 10, txt="Customer Profile", ln=True, align='C')
    pdf.ln(10)

    fields = [
        ("Full Name", customer.get('Name', 'N/A')),
        ("Mobile", customer.get('mobile', 'N/A')),
        ("Address", customer.get('address', 'N/A')),
        ("Reference", customer.get('reference', 'N/A')),
        ("Group", customer.get('group', 'N/A')),
        ("Deposit", customer.get('deposit', 'N/A')),
        ("Total Amount", customer.get('total_price', 0)),
        ("Paid", customer.get('given_price', 0)),
        ("Remaining", customer.get('remaining', 0)),
    ]

    for label, value in fields:
        pdf.cell(200, 10, txt=f"{label}: {value}", ln=True)

    if 'bookings' in customer:
        pdf.ln(5)
        pdf.set_font("Arial", size=11)
        pdf.cell(200, 10, txt="Booking History", ln=True)
        for date, items in customer['bookings'].items():
            pdf.cell(200, 10, txt=f"{date}: {', '.join(items)}", ln=True)

    output = io.BytesIO()
    pdf_bytes = pdf.output(dest='S').encode('latin1')
    output.write(pdf_bytes)
    output.seek(0)


    filename = f"{customer.get('Name', 'customer')}_Profile.pdf"
    return send_file(output, as_attachment=True, download_name=filename)


@auth.route("/catalogue",methods=["GET","POST"])
def catalogue():
    return render_template("catalogue.html")



@auth.route("/bhagwan")
def bhagwan():
    with open('bhagwan.json') as f:
        products = json.load(f)
    return render_template("bhagwan.html", products=products)

@auth.route("/mataji")
def mataji():
    with open('mataji.json') as f:
        products = json.load(f)
    return render_template("mataji.html", products=products)


@auth.route("/superhero")
def superhero():
    with open('superhero.json') as f:
        products = json.load(f)
    return render_template("superhero.html", products=products)

@auth.route("/bird")
def bird():
    with open('birds.json') as f:
        products = json.load(f)
    return render_template("bird.html", products=products)

@auth.route("/nature")
def nature():
    with open('nature.json') as f:
        products = json.load(f)
    return render_template("nature.html", products=products)

@auth.route("/animal")
def animal():
    with open('animal.json') as f:
        products = json.load(f)
    return render_template("animal.html", products=products)

@auth.route("/freedomfighter")
def freedomfighter():
    with open('freedomfighter.json') as f:
        products = json.load(f)
    return render_template("freedomfighter.html", products=products)

@auth.route("/fruit_vegetable")
def fruit_vegetable():
    with open('fruit_vegetable.json') as f:
        products = json.load(f)
    return render_template("fruit_vegetable.html", products=products)

@auth.route("/insect")
def insect():
    with open('insect.json') as f:
        products = json.load(f)
    return render_template("insect.html", products=products)

@auth.route("/cartoon")
def cartoon():
    with open('cartoon.json') as f:
        products = json.load(f)
    return render_template("cartoon.html", products=products)

@auth.route("/profession")
def profession():
    with open('profession.json') as f:
        products = json.load(f)
    return render_template("profession.html", products=products)

@auth.route("/regional")
def regional():
    with open('regional.json') as f:
        products = json.load(f)
    return render_template("regional.html", products=products)

@auth.route("/tiranga")
def tiranga():
    with open('tiranga.json') as f:
        products = json.load(f)
    return render_template("tiranga.html", products=products)

@auth.route("/international")
def international():
    with open('international.json') as f:
        products = json.load(f)
    return render_template("international.html", products=products)

@auth.route("/flex")
def flex():
    with open('flexi.json') as f:
        products = json.load(f)
    return render_template("flex.html", products=products)

@auth.route("/other")
def other():
    with open('other.json') as f:
        products = json.load(f)
    return render_template("other.html", products=products)










