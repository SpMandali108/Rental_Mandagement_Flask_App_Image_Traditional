from flask import Blueprint, render_template, request, session, redirect, url_for, flash
from pymongo import MongoClient
from datetime import datetime, timedelta
from dotenv import load_dotenv
import os
from fpdf import FPDF
import io
from flask import send_file
import json
from flask import send_from_directory
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
            try:
                # Regular bookings from main collection
                customers = collection.find({f"bookings.{date}": {"$exists": True}})
                
                # Fancy bookings from fancy collection (check both start and end dates)
                fcustomers_start = fancy_collection.find({"start_date": date})
                fcustomers_end = fancy_collection.find({"end_date": date})

                # Process regular bookings
                for c in customers:
                    products = c['bookings'].get(date, [])
                    bookings_on_date.append({
                        "Name": c.get("Name", "Unknown"),
                        "mobile": c.get("mobile", "Unknown"),
                        "address": c.get("address", "Not provided"),
                        "deposit": c.get("deposit", "Not provided"),
                        "group": c.get("group", "Not specified"),
                        "reference": c.get("reference", ""),
                        "products": products,
                        "booking_type": "regular"  # Add type identifier
                    })

                # Process fancy bookings - combine start and end date matches
                processed_ids = set()  # To avoid duplicates
                
                # Process bookings that start on this date
                for fc in fcustomers_start:
                    fc_id = str(fc.get("_id", ""))
                    if fc_id not in processed_ids:
                        processed_ids.add(fc_id)
                        start_date = fc.get("start_date", "")
                        end_date = fc.get("end_date", "")
                        
                        # Determine date match type
                        date_match_type = ""
                        if start_date == date and end_date == date:
                            date_match_type = "both"  # Same day booking
                        elif start_date == date:
                            date_match_type = "start"  # Booking starts today
                        
                        bookings_on_date.append({
                            "Name": fc.get("name", "Unknown"),
                            "mobile": fc.get("mobile", "Unknown"),
                            "address": fc.get("Address", "Not provided"),
                            "start_date": start_date,
                            "end_date": end_date,
                            "price": fc.get("price", 0),
                            "costume": fc.get("costume", ""),
                            "details": fc.get("details", ""),
                            "booking_type": "fancy",
                            "date_match_type": date_match_type
                        })
                
                # Process bookings that end on this date (avoid duplicates)
                for fc in fcustomers_end:
                    fc_id = str(fc.get("_id", ""))
                    if fc_id not in processed_ids:
                        processed_ids.add(fc_id)
                        start_date = fc.get("start_date", "")
                        end_date = fc.get("end_date", "")
                        
                        bookings_on_date.append({
                            "Name": fc.get("name", "Unknown"),
                            "mobile": fc.get("mobile", "Unknown"),
                            "address": fc.get("Address", "Not provided"),
                            "start_date": start_date,
                            "end_date": end_date,
                            "price": fc.get("price", 0),
                            "costume": fc.get("costume", ""),
                            "details": fc.get("details", ""),
                            "booking_type": "fancy",
                            "date_match_type": "end"  # Booking ends today
                        })

                # Sort bookings by name for better organization
                bookings_on_date.sort(key=lambda x: x.get('Name', '').lower())
                
            except Exception as e:
                # Log the error and show user-friendly message
                print(f"Error fetching bookings for {date}: {str(e)}")
                flash(f"Error retrieving bookings: {str(e)}", "error")

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

            # Find correct static image
            img_path = None
            if code.startswith("K"):
                img_path = os.path.join(os.path.dirname(__file__), "static", "kediya", f"{code}.webp")
            elif code.startswith("C"):
                img_path = os.path.join(os.path.dirname(__file__), "static", "choli", f"{code}.webp")

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

