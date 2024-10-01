'use client'
from flask import Flask, jsonify, request
from flask_cors import CORS
from datetime import datetime, timedelta
from pymongo import MongoClient
from dotenv import load_dotenv
import os
import pytz
import random
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

app = Flask(__name__)
CORS(app)
load_dotenv()

# Email settings
EMAIL_ADDRESS = os.getenv('EMAIL_USER')  # Your email from environment variable
EMAIL_PASSWORD = os.getenv('EMAIL_PASS')  # Your email password from environment variable

# Get the MongoDB URI from the environment variable
mongo_uri = os.getenv('MONGO_URI')
# MongoDB setup
client = MongoClient(mongo_uri)
db = client.HealthLocker
users_collection = db.users


def send_otp_email(email, otp):
    try:
        subject = "Your OTP for HealthLocker"
        body = f"Your OTP is {otp} "

        # Set up the MIME
        msg = MIMEMultipart()
        msg['From'] = EMAIL_ADDRESS
        msg['To'] = email
        msg['Subject'] = subject
        msg.attach(MIMEText(body, 'plain'))

        # Connect to Gmail's SMTP server
        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls()
        server.login(EMAIL_ADDRESS, EMAIL_PASSWORD)
        text = msg.as_string()
        server.sendmail(EMAIL_ADDRESS, email, text)
        server.quit()

        print("OTP sent successfully.")
        return True
    except Exception as e:
        print(f"Failed to send OTP: {e}")
        return False

def generate_otp():
    """Generate a 6-digit OTP code."""
    return random.randint(100000, 999999)

@app.route('/')
def home():
    return "Hello, Flask on Vercel!"

@app.route('/signup', methods=['POST'])
def signup():
    try:
        user_data = request.get_json()
        if user_data:
            name = user_data.get('name')
            email = user_data.get('email')

            # Ensure name and email are provided
            if not email or not name:
                return jsonify({'error': 'Name and email are required.'}), 400

            # Check if user with the email already exists
            existing_user = users_collection.find_one({'email': email})
            if existing_user:
                return jsonify({'error': 'User with this email already exists.'}), 409

            # Generate OTP and send it via email
            otp_code = generate_otp()
            email_sent = send_otp_email(email, otp_code)

            if not email_sent:
                return jsonify({'error': 'Failed to send OTP email.'}), 500

            # Insert new user (OTP will be stored for validation later)
            result = users_collection.insert_one({
                'name': name,
                'email': email,
                'otp': otp_code,
                'signup_date': datetime.now(pytz.utc),  # Add timestamp for when the user signs up
             })

            # Return success response with the new user's ID
            return jsonify({'success': True, 'user_id': str(result.inserted_id), 'message': 'OTP sent to your email.'}), 201
        else:
            return jsonify({'error': 'Invalid data format.'}), 400
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/verify-otp', methods=['POST'])
def verify_otp():
    try:
        # Get the request data
        data = request.get_json()
        email = data.get('email')
        otp = data.get('otp')

        # Ensure both email and OTP are provided
        if not email or not otp:
            return jsonify({'success': False, 'message': 'Email and OTP are required.'}), 400

        # Check if the user exists with the provided email
        user = users_collection.find_one({'email': email})

        if not user:
            return jsonify({'success': False, 'message': 'User not found.'}), 404

        # Check if the provided OTP matches the one in the database
        if str(user.get('otp')) == str(otp):
            # OTP is correct; remove OTP from the user's record
            users_collection.update_one(
                {'email': email},
                {'$unset': {'otp': ""}}  # Remove OTP field
            )
            return jsonify({'success': True, 'message': 'OTP verified successfully.'}), 200
        else:
            return jsonify({'success': False, 'message': 'Incorrect OTP.'}), 401
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


@app.route('/signin', methods=['POST'])
def signin():
    user_data = request.get_json()
    if not user_data or 'email' not in user_data:
        return jsonify({'error': 'Email is required.'}), 400
    
    email = user_data.get('email')
    
    # Check if user exists
    existing_user = users_collection.find_one({'email': email})
    if existing_user:
        return jsonify({'success': True, 'message': 'Sign in successful.'}), 200
    else:
        return jsonify({'error': 'Email not registered. Please sign up.'}), 404

@app.route('/postrecord', methods=['POST'])
def post_record():
    try:
        data = request.get_json()
        email = data.get('email')
        title = data.get('title')
        category = data.get('category')
        date = data.get('date')
        time = data.get('time')
        image = data.get('image')  # Base64-encoded image

        # Check for missing fields
        if not email or not title or not category or not date or not time or not image:
            return jsonify({'error': 'All fields are required.'}), 400

        # Define the new record
        new_record = {
            'title': title,
            'category': category,
            'date': date,
            'time': time,
            'image': image,  # Store the image as base64
            'created_at': datetime.now(pytz.utc)  # Timestamp for record creation
        }

        # Check if a user with the given email exists
        user = users_collection.find_one({'email': email})

        if user:
            # If the 'records' field exists, append the new record to it
            if 'records' in user:
                users_collection.update_one(
                    {'email': email},
                    {'$push': {'records': new_record}}
                )
            else:
                # If 'records' field does not exist, create it and add the new record
                users_collection.update_one(
                    {'email': email},
                    {'$set': {'records': [new_record]}}
                )
        else:
            # If the user does not exist, return an error
            return jsonify({'error': 'User not found.'}), 404

        return jsonify({'success': True, 'message': 'Record stored successfully.'}), 201

    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/getrecords', methods=['GET'])
def get_records():
    try:
        email = request.args.get('email')  # Get email from query params

        # Fetch the user by email
        user = users_collection.find_one({'email': email}, {'_id': 0, 'records': 1})

        if user and 'records' in user:
            return jsonify({'records': user['records']}), 200
        else:
            return jsonify({'error': 'No records found for this user.'}), 404

    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=80)
