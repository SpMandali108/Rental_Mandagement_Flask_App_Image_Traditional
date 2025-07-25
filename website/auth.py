from flask import Blueprint, render_template, request, session, redirect, url_for, flash
from pymongo import MongoClient
from pywhatkit import sendwhatmsg
from datetime import datetime, timedelta
from dotenv import load_dotenv
import os


auth = Blueprint('auth', __name__)

load_dotenv()

mongoUrl = os.environ.get("client")
client = MongoClient(mongoUrl)
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

def send_whatsapp_message(mobile, name, bookings_dict, total_price, given_price, action_type="booking", old_products=None, new_products=None, date=None):
    remaining = total_price - given_price
    message = ""

    if action_type == "booking":
        formatted_bookings = "\n".join([f"{d}: {', '.join(p)}" for d, p in bookings_dict.items()])
        message = f"""✅ *Booking Confirmation*

Hello {name},

Your booking is confirmed!

📅 Bookings:
{formatted_bookings}
💰 Total: ₹{total_price}
💵 Paid: ₹{given_price}
💸 Remaining: ₹{remaining}

Thank you for choosing Image Traditional!
"""

    elif action_type == "update":
        message = f"""♻️ *Booking Updated*

Hello {name},

Your booking on {date} has been changed.

🔁 From: {', '.join(old_products)}
➡️ To: {', '.join(new_products)}
💰 Total: ₹{total_price}
💵 Paid: ₹{given_price}
💸 Remaining: ₹{remaining}

Thank you for staying with Image Traditional!
"""

    elif action_type == "delete":
        message = f"""🗑️ *Booking Cancelled*

Hello {name},

Your booking on {date} for product '{old_products[0]}' has been removed.

💰 Total: ₹{total_price}
💵 Paid: ₹{given_price}
💸 Remaining: ₹{remaining}

We hope to serve you again!
"""

    elif action_type == "payment":
        message = f"""💳 *Payment Received*

Hello {name},

We have received your payment.

💰 Total: ₹{total_price}
💵 Paid: ₹{given_price}
💸 Remaining: ₹{remaining}

Thank you for your prompt payment!
"""

    try:
        send_time = datetime.now() + timedelta(minutes=1,seconds =10)
        sendwhatmsg(
            f"+91{mobile[-10:]}",
            message,
            send_time.hour,
            send_time.minute,
            wait_time=30
            ,
            tab_close=True,
            close_time=8
        )
    except Exception as e:
        print(f"Error sending WhatsApp message to {mobile}:", e)



def send_whatsapp_message_fancy(mobile, name, bookings_dict=None, price=0, action_type="booking"):
    message = ""

    if action_type == "booking":
        formatted_bookings = "\n".join([f"📅 {d}:\n   🎭 {', '.join(p)}" for d, p in bookings_dict.items()])
        message = f"""🌟 *Image Traditional* 🌟

✅ *Booking Confirmation*

Hey *{name}* ✨,

📝 Your booking has been successfully *confirmed*! Here's the summary:

{formatted_bookings}

💵 *Total*: ₹{price}

🙏 Thank you for choosing us!
We’re excited to dress you in style! 💃
"""

    try:
        send_time = datetime.now() + timedelta(minutes=1,seconds=10)
        sendwhatmsg(
            f"+91{mobile[-10:]}",
            message,
            send_time.hour,
            send_time.minute,
            wait_time=30,
            tab_close=True,
            close_time=8
        )
    except Exception as e:
        print(f"❌ Error sending WhatsApp message to {mobile}: {e}")



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
    if not session.get('logged_in'):
        return redirect(url_for('auth.login'))

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





    return render_template("total.html", total_bookings=total_bookings, total_fancy_bookings=total_fancy_bookings)

