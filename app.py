from flask import Flask, jsonify, request
from flask_cors import CORS
from datetime import datetime
from pymongo import MongoClient, DESCENDING
from dotenv import load_dotenv
import os
import pytz
from bson import ObjectId

MAX_RETRIES = 3
RETRY_DELAY_SECONDS = 1

app = Flask(__name__)
CORS(app)
load_dotenv()

# Get the MongoDB URI from the environment variable
mongo_uri = os.getenv('MONGO_URI')
# MongoDB setup
client = MongoClient(mongo_uri)
db = client.HealthLocker
users_collection = db.users

@app.route('/')
def home():
    return "Hello, Flask on Vercel!"

@app.route('/signup', methods=['POST'])
def signup():
    try:
        user_data = request.get_json()
        if user_data:
            email = user_data.get('email')
            
            # Ensure email is provided
            if not email:
                return jsonify({'error': 'Email is required.'}), 400

            # Check if user with the email already exists
            existing_user = users_collection.find_one({'email': email})
            if existing_user:
                return jsonify({'error': 'User with this email already exists.'}), 409
            
            # Insert new user
            result = users_collection.insert_one({
                'email': email,
                'signup_date': datetime.now(pytz.utc)  # Add timestamp for when the user signs up
            })
            
            # Return success response with the new user's ID
            return jsonify({'success': True, 'user_id': str(result.inserted_id)}), 201
        else:
            return jsonify({'error': 'Invalid data format.'}), 400
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/signin', methods=['POST'])
def signin():
    user_data = request.get_json()
    if not user_data or 'email' not in user_data:
        return jsonify({'error': 'Email is required.'}), 400
    
    email = user_data.get('email')
    
    # Check if user exists
    existing_user = users_collection.find_one({'email': email})
    if existing_user:
        # Get the current timestamp in IST
        us_time_zone = pytz.timezone('America/New_York')
        current_timestamp = datetime.now(us_time_zone)
        formatted_timestamp = current_timestamp.isoformat()
        
        # Update the user's document with the current timestamp
        users_collection.update_many(
            {'email': email},
            {'$set': {'last_signin': formatted_timestamp}}
        )
        return jsonify({'success': True, 'message': 'Sign in successful.'}), 200
    else:
        return jsonify({'error': 'Email not registered. Please sign up.'}), 404


@app.route('/Club_users', methods=['GET'])
def get_users():
    try:
        # Fetch all records from the collection, sorted by last_signin in descending order
        users = users_collection.find({}, {'_id': 0}).sort('last_signin',DESCENDING)  # Exclude the _id field
        # Convert MongoDB documents to a list of dictionaries
        users_list = list(users)
        return jsonify(users_list)
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=80)