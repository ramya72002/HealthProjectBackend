import re
from flask import Flask, jsonify, request, render_template
from flask_cors import CORS
from pymongo import MongoClient
from dotenv import load_dotenv
import uuid
import os
import pytz
import random
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import datetime
from werkzeug.security import generate_password_hash, check_password_hash
import boto3
from datetime import datetime, timedelta
import secrets
import random
import smtplib
from flask import redirect, url_for

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
password_reset_tokens_collection=db.password_reset_tokens

# AWS S3 settings 
AWS_ACCESS_KEY_ID =  os.getenv('AWS_ACCESS_KEY_ID') 
AWS_SECRET_ACCESS_KEY =  os.getenv('AWS_SECRET_ACCESS_KEY') 
S3_BUCKET =  os.getenv('AWS_BUCKET_NAME') 

# Initialize the S3 client
s3 = boto3.client(
    's3',
    aws_access_key_id=AWS_ACCESS_KEY_ID,
    aws_secret_access_key=AWS_SECRET_ACCESS_KEY
)

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
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'pdf'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@app.route('/upload', methods=['POST'])
def upload_file():
    if 'file' not in request.files:
        return jsonify({'error': 'No file part'}), 400
    
    file = request.files['file']

    if file.filename == '':
        return jsonify({'error': 'No selected file'}), 400

    # Validate file type
    if not allowed_file(file.filename):
        return jsonify({'error': 'File type not allowed. Only images and PDFs are accepted.'}), 400
    
    try:
        extension = os.path.splitext(file.filename)[1]
        unique_filename = f"{uuid.uuid4()}{extension}"
        s3.upload_fileobj(file, S3_BUCKET, unique_filename)
        object_url = f"https://{S3_BUCKET}.s3.amazonaws.com/{unique_filename}"

        return jsonify({"file_url": object_url}), 200

    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/multi_upload', methods=['POST'])
def multi_upload():
    if 'files' not in request.files:
        return jsonify({'error': 'No files part'}), 400

    files = request.files.getlist('files')  # Retrieve all files in the 'files' field

    if not files:
        return jsonify({'error': 'No selected files'}), 400
    
    image_urls = []

    try:
        for file in files:
            if file.filename == '':
                return jsonify({'error': 'One or more files are empty'}), 400

            # Generate a unique filename for each file
            extension = os.path.splitext(file.filename)[1]
            unique_filename = f"{uuid.uuid4()}{extension}"

            # Upload each file to S3 with a unique filename
            s3.upload_fileobj(file, S3_BUCKET, unique_filename)

            # Construct the public URL for each uploaded file
            object_url = f"https://{S3_BUCKET}.s3.amazonaws.com/{unique_filename}"
            image_urls.append(object_url)

        return jsonify({"image_urls": image_urls}), 200

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route("/register", methods=["POST"])
def register():
    data = request.get_json()
    name = data.get('name')
    email = data.get('email')
    password = data.get('password')

    if not name or not email or not password:
        return jsonify({"success": False, "message": "All fields are required."}), 400

    email_regex = r'^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$'
    if not re.match(email_regex, email):
        return jsonify({"success": False, "message": "Invalid email format."}), 400

    existing_user = users_collection.find_one({"email": email})
    if existing_user:
        return jsonify({"success": False, "message": "Email already registered."}), 400

    hashed_password = generate_password_hash(password, method='pbkdf2:sha256')

    # Generate a unique user_id
    user_id = str(uuid.uuid4())

    new_user = {
        "user_id": user_id,
        "name": name,
        "email": email,
        "password": hashed_password,
        "created_at": datetime.datetime.utcnow()
    }

    users_collection.insert_one(new_user)

    return jsonify({"success": True, "message": "User registered successfully.", "user_id": user_id}), 201

@app.route("/login", methods=["POST"])
def login():
    data = request.get_json()
    email = data.get('email')
    password = data.get('password')

    if not email or not password:
        return jsonify({"success": False, "message": "Email and password are required."}), 400

    user = users_collection.find_one({"email": email})
    if not user:
        return jsonify({"success": False, "message": "Email not registered."}), 400

    if not check_password_hash(user['password'], password):
        return jsonify({"success": False, "message": "Incorrect password."}), 400

    user_data = {
        "id": str(user['_id']),
        "user_id":user["user_id"],
        "name": user['name'],
        "email": user['email'],
        "created_at": user.get('created_at')
    }

    return jsonify({"success": True, "message": "Login successful.", "user": user_data}), 200



@app.route('/forgot-password', methods=['POST'])
def forgot_password():
    data = request.json
    email = data.get('email')

    if not email:
        return jsonify({"error": "Email is required"}), 400

    # Check if the user exists
    user = users_collection.find_one({"email": email})
    if not user:
        return jsonify({"error": "User not found"}), 404

    # Generate a unique reset token
    reset_token = secrets.token_urlsafe(32)
    expiration_time = datetime.utcnow() + timedelta(hours=1)  # Token expires in 1 hour

    # Save the token in the database
    password_reset_tokens_collection.insert_one({
        "email": email,
        "token": reset_token,
        "expires_at": expiration_time
    })

    # Send the reset link to the user's email
    reset_link = f"https://bcc-facility-rental.vercel.app/forgotpasswrod?token={reset_token}"
    email_body = f"""
    <p>You requested a password reset. Click the link below to reset your password:</p>
    <p><a href="{reset_link}">Reset Password</a></p>
    <p>This link will expire in 1 hour.</p>
    """

    try:
        # Send email
        msg = MIMEText(email_body, "html")
        msg["Subject"] = "Password Reset Request"
        msg["From"] = "nvisionwebsiterequest@gmail.com"
        msg["To"] = email

        with smtplib.SMTP('smtp.gmail.com', 587) as server:
            server.starttls()
            server.login("nvisionwebsiterequest@gmail.com", "qulz fnvb yfjh phgu")
            server.sendmail("nvisionwebsiterequest@gmail.com", [email], msg.as_string())

        return jsonify({"message": "Password reset link sent to your email"}), 200
    except Exception as e:
        return jsonify({"error": "Failed to send email", "details": str(e)}), 500
@app.route('/reset-password', methods=['POST'])
def reset_password():
    data = request.json
    token = data.get('token')
    new_password = data.get('new_password')

    if not token or not new_password:
        return jsonify({"error": "Token and new password are required"}), 400

    # Find the token in the database
    reset_record = password_reset_tokens_collection.find_one({"token": token})

    if not reset_record:
        return jsonify({"error": "Invalid or expired token"}), 400

    # Check if the token has expired
    if datetime.utcnow() > reset_record["expires_at"]:
        return jsonify({"error": "Token has expired"}), 400

    # Hash the new password before saving it
    hashed_password = generate_password_hash(new_password, method='pbkdf2:sha256')

    # Update the user's password in the database
    users_collection.update_one(
        {"email": reset_record["email"]},
        {"$set": {"password": hashed_password}}
    )

    # Delete the used token
    password_reset_tokens_collection.delete_one({"token": token})

    return jsonify({"message": "Password reset successfully"}), 200
@app.route("/uploads", methods=["POST"])
def upload_content():
    try:
        data = request.get_json()
        email = data.get('email')
        image_url = data.get('image_url')
        title = data.get('title')
        category = data.get('category')
        date_time = data.get('date_time')

        if not all([email, image_url, title, category, date_time]):
            return jsonify({"success": False, "message": "All fields are required."}), 400

        user = users_collection.find_one({"email": email})
        if not user:
            return jsonify({"success": False, "message": "Email not registered."}), 400

        new_upload = {
            "image_url": image_url,
            "title": title,
            "category": category,
            "date_time": str(date_time)
        }

        update_result = users_collection.update_one(
            {"email": email},
            {"$push": {"uploads": new_upload}}
        )

        return jsonify({"success": True, "message": "Upload added successfully.", "upload": new_upload}), 200

    except Exception as e:
        return jsonify({"success": False, "message": "An error occurred while processing the request.", "error": str(e)}), 500

@app.route("/uploads_wrt_userId", methods=["POST"])
def uploads_wrt_userId():
    try:
        data = request.get_json()
        user_id = data.get('user_id')
        image_urls = data.get('image_urls')  # Expecting a list of image URLs
        title = data.get('title', '')  # Default to empty string if title is not provided
        category = data.get('category', '')  # Default to empty string if category is not provided
        date_time = data.get('date_time','')

        if not all([user_id, image_urls]):
            return jsonify({"success": False, "message": "User ID, image URLs, and date/time are required."}), 400

        if not isinstance(image_urls, list):
            return jsonify({"success": False, "message": "Image URLs should be a list."}), 400

        user = users_collection.find_one({"user_id": user_id})
        if not user:
            return jsonify({"success": False, "message": "User not found."}), 400

        new_uploads = [{
            "image_url": image_url,
            "title": title,
            "category": category,
            "date_time": str(date_time)
        } for image_url in image_urls]

        update_result = users_collection.update_one(
            {"user_id": user_id},
            {"$push": {"uploads": {"$each": new_uploads}}}
        )

        if update_result.matched_count == 0:
            return jsonify({"success": False, "message": "Failed to update user uploads."}), 400

        return jsonify({"success": True, "message": "Uploads added successfully.", "uploads": new_uploads}), 200

    except Exception as e:
        return jsonify({"success": False, "message": "An error occurred while processing the request.", "error": str(e)}), 500


@app.route("/medications_wrt_userId", methods=["POST"])
def medications_wrt_userId():
    try:
        data = request.get_json()
        user_id = data.get('user_id')
        medication_name = data.get('medication_name')
        frequency = data.get('frequency')
        schedule = data.get('schedule')  # List of schedule times
        start_date = data.get('start_date')
        end_date = data.get('end_date')
        count = data.get('count', None)  # For "Every x days" frequency
        selected_days = data.get('selected_days', {})  # For "Day of the week" frequency
        selected_dates = data.get('selected_dates', [])  # For "Day of the month" frequency

        if not all([user_id, medication_name, frequency, schedule, start_date, end_date]):
            return jsonify({"success": False, "message": "User ID, medication name, frequency, schedule, start date, and end date are required."}), 400

        user = users_collection.find_one({"user_id": user_id})
        if not user:
            return jsonify({"success": False, "message": "User not found."}), 400

        # Generate a unique 6-digit ID
        def generate_unique_id():
            while True:
                # Generate a random 6-digit number
                medication_id = random.randint(100000, 999999)
                # Check if the ID already exists in the user's medications
                existing_medication = users_collection.find_one(
                    {"user_id": user_id, "medications.medication_id": medication_id}
                )
                if not existing_medication:
                    return medication_id

        medication_id = generate_unique_id()

        # Create the medication record
        medication_data = {
            "medication_id": medication_id,  # Add the unique medication ID
            "medication_name": medication_name,
            "frequency": frequency,
            "schedule": schedule,
            "start_date": start_date,
            "end_date": end_date,
            "count": count,
            "selected_days": selected_days,
            "selected_dates": selected_dates
        }

        # Add the medication data to the user's record
        update_result = users_collection.update_one(
            {"user_id": user_id},
            {"$push": {"medications": medication_data}}  # Assuming 'medications' field in user document
        )

        if update_result.matched_count == 0:
            return jsonify({"success": False, "message": "Failed to add medication."}), 400

        return jsonify({"success": True, "message": "Medication added successfully.", "medication": medication_data}), 200

    except Exception as e:
        return jsonify({"success": False, "message": "An error occurred while processing the request.", "error": str(e)}), 500

@app.route("/delete_medication_wrt_id", methods=["POST"])
def delete_medication_id():
    try:
        data = request.get_json()
        user_id = data.get('user_id')
        medication_id = data.get('medication_id')

        if not all([user_id, medication_id]):
            return jsonify({"success": False, "message": "User ID and medication ID are required."}), 400

        # Find the user and the medication to be deleted
        user = users_collection.find_one({"user_id": user_id})
        if not user:
            return jsonify({"success": False, "message": "User not found."}), 400

        # Remove the medication from the user's medications list using medication_id
        update_result = users_collection.update_one(
            {"user_id": user_id},
            {"$pull": {"medications": {"medication_id": medication_id}}}
        )

        if update_result.matched_count == 0:
            return jsonify({"success": False, "message": "Failed to delete medication. Medication ID might not exist."}), 400

        return jsonify({"success": True, "message": "Medication deleted successfully."}), 200

    except Exception as e:
        return jsonify({"success": False, "message": "An error occurred while processing the request.", "error": str(e)}), 500


@app.route("/get_medications_wrt_userId", methods=["POST"])
def get_medications_wrt_userId():
    try:
        data = request.get_json()
        user_id = data.get('user_id')

        if not user_id:
            return jsonify({"success": False, "message": "User ID is required."}), 400

        user = users_collection.find_one({"user_id": user_id}, {"_id": 0, "medications": 1})
        if not user:
            return jsonify({"success": True, "message": "medications not found."}), 200

        medications = user.get("medications", [])

        return jsonify({"success": True, "message": "Medications retrieved successfully.", "medications": medications}), 200

    except Exception as e:
        return jsonify({"success": False, "message": "An error occurred while processing the request.", "error": str(e)}), 500

@app.route("/update_uploads_t&c", methods=["PUT"])
def update_uploads_t_c():
    try:
        data = request.get_json()
        user_id = data.get('user_id')
        image_url = data.get('image_url')  # Single image URL for the update
        title = data.get('title', '')  # New title to be updated
        category = data.get('category', '')  # New category to be updated

        if not all([user_id, image_url, title, category]):
            return jsonify({"success": False, "message": "User ID, image URL, title, and category are required."}), 400

        # Find the user and check if the image exists in their uploads
        user = users_collection.find_one({"user_id": user_id, "uploads.image_url": image_url})
        if not user:
            return jsonify({"success": False, "message": "User or image not found."}), 404

        # Update the title and category for the specific image
        update_result = users_collection.update_one(
            {"user_id": user_id, "uploads.image_url": image_url},
            {"$set": {"uploads.$.title": title, "uploads.$.category": category}}
        )

        if update_result.matched_count == 0:
            return jsonify({"success": False, "message": "Failed to update the upload details."}), 400

        return jsonify({"success": True, "message": "Upload details updated successfully."}), 200

    except Exception as e:
        return jsonify({"success": False, "message": "An error occurred while processing the request.", "error": str(e)}), 500

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

@app.route('/get_uploaded_records', methods=['GET'])
def get_records_records():
    try:
        email = request.args.get('email')  # Get email from query params

        # Fetch the user by email
        user = users_collection.find_one({'email': email}, {'_id': 0, 'uploads': 1})

        if user and 'uploads' in user:
            return jsonify({'uploads': user['uploads']}), 200
        else:
            return jsonify({'error': 'No records found for this user.'}), 200

    except Exception as e:
        return jsonify({'error': str(e)}), 500
    
if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=80)
