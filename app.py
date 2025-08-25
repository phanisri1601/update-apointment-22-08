from flask import Flask, render_template, request, jsonify, redirect, url_for, session
import google.generativeai as genai
from dotenv import load_dotenv
import os
import logging
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
import pytz
from icalendar import Calendar, Event
import json
import csv
import random
from twilio.rest import Client
from twilio.twiml.voice_response import VoiceResponse, Gather
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
import pickle
from functools import lru_cache
import time
import uuid
from collections import Counter, defaultdict
from functools import wraps

# Firebase Admin SDK
try:
    import firebase_admin
    from firebase_admin import credentials as fb_credentials
    from firebase_admin import db as fb_db
except Exception:
    firebase_admin = None
    fb_credentials = None
    fb_db = None

# Configure logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv('FLASK_SECRET_KEY', 'dev-secret-change-me')

# Initialize Firebase (Realtime Database) for leads
rtdb_available = False
rtdb_url = None
try:
    if firebase_admin is not None:
        cred = None

        # 1) Prefer base64 JSON from env
        fb_cred_b64 = os.getenv('FIREBASE_CREDENTIALS_JSON_B64')
        if fb_cred_b64:
            try:
                decoded = json.loads(
                    __import__('base64').b64decode(fb_cred_b64).decode('utf-8')
                )
                cred = fb_credentials.Certificate(decoded)
                try:
                    logger.info(f"Firebase SA: project={decoded.get('project_id')} email={decoded.get('client_email')}")
                except Exception:
                    pass
            except Exception as e:
                logger.error(f"Failed to decode FIREBASE_CREDENTIALS_JSON_B64: {e}")

        # 2) Then raw JSON string from env
        if cred is None:
            fb_cred_json = os.getenv('FIREBASE_CREDENTIALS_JSON')
            if fb_cred_json:
                try:
                    parsed = json.loads(fb_cred_json)
                    cred = fb_credentials.Certificate(parsed)
                    try:
                        logger.info(f"Firebase SA: project={parsed.get('project_id')} email={parsed.get('client_email')}")
                    except Exception:
                        pass
                except Exception as e:
                    logger.error(f"Failed to parse FIREBASE_CREDENTIALS_JSON: {e}")

        # 3) Finally, credentials file path from env
        if cred is None:
            cred_file_path = os.getenv('FIREBASE_CREDENTIALS_FILE')
            if cred_file_path and os.path.exists(cred_file_path):
                try:
                    cred = fb_credentials.Certificate(cred_file_path)
                except Exception as e:
                    logger.error(f"Failed to load Firebase credentials from file: {e}")

        if cred is not None:
            rtdb_url = os.getenv('FIREBASE_DATABASE_URL')
            if not rtdb_url:
                logger.warning('FIREBASE_DATABASE_URL not set. RTDB features will be disabled.')
            else:
                try:
                    # Initialize only once
                    if not firebase_admin._apps:
                        firebase_admin.initialize_app(cred, { 'databaseURL': rtdb_url })
                    logger.info(f"Firebase initialized successfully with database: {rtdb_url}")
                    rtdb_available = True
                except Exception as e:
                    logger.error(f"Failed to initialize Firebase: {e}")
                    rtdb_available = False
        else:
            logger.warning('Firebase credentials not provided. RTDB features will be disabled.')
            rtdb_available = False
    else:
        logger.warning('firebase_admin is not installed. Leads dashboard will be disabled until installed.')
except Exception as e:
    logger.error(f"Unexpected Firebase init error: {e}")
    rtdb_available = False

# Google Sheets setup
SCOPES = ['https://www.googleapis.com/auth/spreadsheets']
SPREADSHEET_ID = '1KzT0Idmu420OWlLiH6cKcxLZv_zjIbmNq6HjXohKGp4'  # Your Google Sheet ID
RANGE_NAME = 'Calls!A:E'  # Sheet name and range

 # Configure Gemini
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY', 'AIzaSyAIAqbokZhxpbstxZ8ZUOG1WGrVHrjK8_k')
genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel('gemini-2.0-flash')

# Configure Twilio
TWILIO_ACCOUNT_SID = os.getenv('TWILIO_ACCOUNT_SID', 'AC98028fc853ea846cf8926582807b9e49')
TWILIO_AUTH_TOKEN = os.getenv('TWILIO_AUTH_TOKEN', 'f262ad9c47a78436a1f90462e61c15bc')
TWILIO_PHONE_NUMBER = os.getenv('TWILIO_PHONE_NUMBER', '+13154440346')
twilio_client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)

# Store appointments in memory (in production, use a database)
appointments = []

# Load IM Solutions content from JSON
with open('imsolutions_content.json', 'r', encoding='utf-8') as f:
    IM_SOLUTIONS_DATA = json.load(f)

# Cache for Gemini responses
response_cache = {}
CACHE_EXPIRY = 3600  # Cache expiry time in seconds (1 hour)

def get_cached_response(user_input):
    """Get cached response if available and not expired"""
    current_time = time.time()
    if user_input in response_cache:
        cached_time, cached_response = response_cache[user_input]
        if current_time - cached_time < CACHE_EXPIRY:
            return cached_response
    return None

def cache_response(user_input, response):
    """Cache the response with current timestamp"""
    response_cache[user_input] = (time.time(), response)

def _services_reply_from_json() -> str:
    online = IM_SOLUTIONS_DATA.get('services', {}).get('online_services', [])
    offline = IM_SOLUTIONS_DATA.get('services', {}).get('offline_services', [])
    online_str = ', '.join(online[:6]) if online else 'SEO, SEM, Social media, Websites'
    offline_str = ', '.join(offline[:6]) if offline else 'Bus ads, Mall ads, Outdoor'
    return f"🧠 Online: {online_str}. 🏢 Offline: {offline_str}. Want a quick plan or a free audit?"

def _blogs_reply_from_json() -> str:
    blogs = IM_SOLUTIONS_DATA.get('blogs', [])
    if isinstance(blogs, list) and blogs:
        titles = [b.get('title') for b in blogs if isinstance(b, dict) and b.get('title')]
        top = ', '.join(titles[:5]) if titles else 'brand stories and growth guides'
        return f"📝 We share {top}. Want us to draft a blog outline for your niche?"
    return "📝 We can write fresh, engaging blogs for your audience. What topic should we start with?"

def _recent_blogs_reply(limit: int = 5) -> str:
    blogs = IM_SOLUTIONS_DATA.get('blogs', [])
    items = []
    if isinstance(blogs, list):
        for b in blogs[:limit]:
            if isinstance(b, dict):
                title = b.get('title') or b.get('name') or 'Blog'
                date = b.get('date') or b.get('published_at') or ''
                items.append(f"• {title}{(' – ' + date) if date else ''}")
    if not items:
        return "📝 No blogs listed yet. Want us to spin up a fresh content calendar for you?"
    return "📝 Recent blogs:\n" + "\n".join(items) + "\nWant a link or a quick summary?"

# Common questions and their responses
COMMON_QUESTIONS = {
    "what are your services": "",
    "where are you located": f"We are headquartered in {IM_SOLUTIONS_DATA['company_info']['location']} with offices in {', '.join(IM_SOLUTIONS_DATA['company_info']['offices'])}.",
    "how can i contact you": "I'd be happy to help you get in touch with our team. Please let me know what specific information or assistance you need, and I can guide you to the right department or provide relevant details.",
    "what is your vision": IM_SOLUTIONS_DATA['vision']
}

def get_google_sheets_service():
    creds = None
    if os.path.exists('token.pickle'):
        with open('token.pickle', 'rb') as token:
            creds = pickle.load(token)
    
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                'credentials.json', SCOPES)
            creds = flow.run_local_server(port=0)
        with open('token.pickle', 'wb') as token:
            pickle.dump(creds, token)

    return build('sheets', 'v4', credentials=creds)

def save_call_summary(call_sid, phone_number, duration, summary):
    try:
        service = get_google_sheets_service()
        values = [[
            datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            call_sid,
            phone_number,
            duration,
            summary
        ]]
        body = {
            'values': values
        }
        result = service.spreadsheets().values().append(
            spreadsheetId=SPREADSHEET_ID,
            range=RANGE_NAME,
            valueInputOption='RAW',
            body=body
        ).execute()
        logger.info(f"Call summary saved to Google Sheets: {result}")
        return True
    except Exception as e:
        logger.error(f"Error saving call summary: {str(e)}")
        return False

# Store call summaries in memory (in case Google Sheets fails)
call_summaries = {}

def get_chatgpt_response(user_input, history=None):
    try:
        logger.debug(f"Processing input: {user_input}")
        
        # Check for common questions first
        user_input_lower = user_input.lower().strip()
        for question, response in COMMON_QUESTIONS.items():
            if question in user_input_lower:
                return response

        # (Removed) keyword short-circuit for services to ensure dynamic, JSON-driven answers

        # Check cache
        cached_response = get_cached_response(user_input)
        if cached_response:
            logger.debug("Returning cached response")
            return cached_response

        # Prepare recent context (last few user/bot turns)
        formatted_context = ''
        if history and isinstance(history, list):
            tail = history[-6:]
            lines = []
            for h in tail:
                role = h.get('role', 'user')
                content = h.get('content', '')
                if content:
                    lines.append(f"{role.capitalize()}: {content}")
            if lines:
                formatted_context = "\n\nRecent conversation (most recent last):\n" + "\n".join(lines)

        # Contact and company details from JSON
        contact = IM_SOLUTIONS_DATA.get('contact', {}).get('corporate_office', {})
        phone = contact.get('phone', '')
        email = contact.get('email', '')
        address = contact.get('address', '')
        website = IM_SOLUTIONS_DATA.get('website', '') if isinstance(IM_SOLUTIONS_DATA, dict) else ''

        # Extract dynamic knowledge from JSON
        services_online = IM_SOLUTIONS_DATA.get('services', {}).get('online_services', [])
        services_offline = IM_SOLUTIONS_DATA.get('services', {}).get('offline_services', [])
        case_studies = IM_SOLUTIONS_DATA.get('case_studies', []) if isinstance(IM_SOLUTIONS_DATA.get('case_studies', []), list) else []
        case_snippets = []
        for cs in case_studies[:3]:
            name = cs.get('client', 'Client')
            win = cs.get('result', '')
            brief = cs.get('summary', '')
            if win or brief:
                case_snippets.append(f"- {name}: {win or brief}")
        knowledge_block = f"""
Knowledge:
- Online services: {', '.join(services_online)}
- Offline services: {', '.join(services_offline)}
- Case studies:
{chr(10).join(case_snippets) if case_snippets else '- (no case studies listed)'}
- Contact: phone {phone}, email {email}, address {address}, website {website}
"""

        # Create concise, witty prompt with JSON-powered facts
        prompt = f"""You are a witty, professional assistant for {IM_SOLUTIONS_DATA['company_info']['name']}.

Tone and style:
- Short, funny, and encouraging. Use simple English.
- HARD LIMIT: 1–3 sentences total.
- Connect to the user's previous questions when helpful.
- Offer one short follow-up question.
- Always include 1–3 relevant emojis in every reply (no more than 3).

Company facts:
- Type: {IM_SOLUTIONS_DATA['company_info']['type']} | Founded: {IM_SOLUTIONS_DATA['company_info']['founded']} | Location: {IM_SOLUTIONS_DATA['company_info']['location']}
- Top services: {', '.join(IM_SOLUTIONS_DATA['services']['online_services'][:6])}

{knowledge_block}
User question: {user_input}
{formatted_context}

Instructions:
- Answer using the Knowledge section above (treat it as your source of truth).
- If the question is off-topic, gently steer back to our services with humor.
- End with a tiny prompt that invites the next step."""

        response = model.generate_content(prompt)
        
        logger.debug(f"Received response from Gemini")
        reply = response.text.strip()
        reply = reply.replace('*', '')
        
        # Enforce ultra-short replies: max 3 sentences
        import re
        compact = re.sub(r"\s+", " ", reply)
        sentences = re.split(r"(?<=[.!?])\s+", compact)
        reply = " ".join(sentences[:3]).strip()

        # Cache the response
        cache_response(user_input, reply)
        
        return reply
    except Exception as e:
        error_msg = f"Error calling Gemini API: {str(e)}"
        logger.error(error_msg)
        return f"Oops! 🤖 My marketing brain glitched for a sec. Give me a moment and try that again! 🔄"

@app.route('/')
def index():
    # Ensure each browser session has a stable session_id
    if not session.get('session_id'):
        session['session_id'] = f"session_{int(time.time())}_{random.randint(1000,9999)}"
    return render_template('index.html')

def login_required(view_func):
    @wraps(view_func)
    def wrapped(*args, **kwargs):
        if not session.get('logged_in'):
            next_url = request.path
            return redirect(url_for('login', next=next_url))
        return view_func(*args, **kwargs)
    return wrapped

@app.route('/login', methods=['GET', 'POST'])
def login():
    error = None
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()
        if username == 'imsol' and password == 'password':
            session['logged_in'] = True
            dest = request.args.get('next') or url_for('dashboard')
            return redirect(dest)
        else:
            error = 'Invalid credentials'
    return render_template('login.html', error=error)

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/send_message', methods=['POST'])
def send_message():
    try:
        user_message = request.json['message']
        logger.debug(f"Received message from user: {user_message}")
        
        # Maintain a short rolling history in session for context
        chat_hist = session.get('chat_history', [])
        chat_hist.append({'role': 'user', 'content': user_message})
        session['chat_history'] = chat_hist[-10:]
        
        bot_response = get_chatgpt_response(user_message, history=session.get('chat_history', []))
        # If user asked about blogs explicitly, send a recent list for clarity
        try:
            if 'blog' in user_message.lower():
                bot_response = _recent_blogs_reply()
        except Exception:
            pass
        logger.debug(f"Sending response to user: {bot_response}")
        
        # Append bot turn
        chat_hist = session.get('chat_history', [])
        chat_hist.append({'role': 'assistant', 'content': bot_response})
        session['chat_history'] = chat_hist[-10:]
        
        # Store conversation in Firebase
        if rtdb_available:
            try:
                conversation_id = str(uuid.uuid4())
                user_name = session.get('name') or request.json.get('user_details', {}).get('name') or 'Anonymous'
                user_email = session.get('email') or request.json.get('user_details', {}).get('email') or ''
                user_phone = session.get('phone') or request.json.get('user_details', {}).get('phone') or ''
                conversation_data = {
                    'id': conversation_id,
                    'user_message': user_message,
                    'bot_response': bot_response,
                    'timestamp': int(time.time() * 1000),
                    'session_id': session.get('session_id', 'default'),
                    'user_details': {
                        'name': user_name,
                        'email': user_email,
                        'phone': user_phone
                    }
                }
                
                safe_firebase_operation(
                    lambda: fb_db.reference('conversations').child(conversation_id).set(conversation_data)
                )
                
            except Exception as e:
                logger.warning(f"Failed to save conversation to RTDB: {e}")
        
        return jsonify({'response': bot_response})
    except Exception as e:
        error_msg = f"Error processing message: {str(e)}"
        logger.error(error_msg)
        return jsonify({'response': f"Error: {str(e)}"}), 500

@app.route('/schedule_appointment', methods=['POST'])
def schedule_appointment():
    try:
        data = request.json
        title = data.get('title')
        time = data.get('time')
        notes = data.get('notes', '')

        if not title or not time:
            return jsonify({'error': 'Missing required fields'}), 400

        # Convert time string to datetime object
        appointment_time = datetime.fromisoformat(time.replace('Z', '+00:00'))
        
        # Check for existing appointments at the same time
        existing_appointments = []
        try:
            with open('appointments.csv', 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                existing_appointments = list(reader)
        except FileNotFoundError:
            pass

        # Check if there's any appointment at the same time
        for existing in existing_appointments:
            existing_time = datetime.fromisoformat(existing['time'].replace('Z', '+00:00'))
            if existing_time == appointment_time:
                return jsonify({
                    'error': 'This time slot is already booked. Please choose a different time.',
                    'existing_appointment': existing
                }), 409  # 409 Conflict status code

        # Generate a unique ID (timestamp + random number)
        timestamp = int(datetime.now().timestamp())
        random_num = random.randint(1000, 9999)
        appointment_id = f"APT-{timestamp}-{random_num}"
        
        # Create appointment object - get user info from request or session
        user_info = {
            'name': data.get('user_name') or session.get('name', ''),
            'email': data.get('user_email') or session.get('email', ''),
            'phone': data.get('user_phone') or session.get('phone', ''),
            'company': data.get('user_company', '')
        }
        
        # If no user name is available, try to generate a meaningful identifier
        if not user_info['name']:
            # Try to get user info from request headers or other sources
            user_agent = request.headers.get('User-Agent', '')
            if 'bot' in user_agent.lower():
                user_info['name'] = 'Chatbot User'
            elif user_agent:
                user_info['name'] = 'Web User'
            else:
                user_info['name'] = 'Anonymous User'
        appointment = {
            'id': appointment_id,
            'title': title,
            'time': appointment_time.isoformat(),
            'notes': notes,
            'status': 'scheduled',
            'user': user_info
        }
        
        # Add to appointments list
        appointments.append(appointment)
        
        # Save to CSV file
        csv_file = 'appointments.csv'
        file_exists = os.path.isfile(csv_file)
        with open(csv_file, 'a', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(
                f,
                fieldnames=['id', 'title', 'time', 'notes', 'status', 'user_name', 'user_email', 'user_phone', 'user_company']
            )
            if not file_exists:
                writer.writeheader()
            writer.writerow({
                'id': appointment['id'],
                'title': appointment['title'],
                'time': appointment['time'],
                'notes': appointment['notes'],
                'status': appointment['status'],
                'user_name': user_info.get('name', ''),
                'user_email': user_info.get('email', ''),
                'user_phone': user_info.get('phone', ''),
                'user_company': user_info.get('company', '')
            })
        
        # Create iCalendar event
        cal = Calendar()
        event = Event()
        event.add('summary', title)
        event.add('dtstart', appointment_time)
        event.add('description', notes)
        
        cal.add_component(event)
        
        # Save to file (in production, use a database)
        with open(f'appointments/{appointment["id"]}.ics', 'wb') as f:
            f.write(cal.to_ical())
        
        # Save to Firebase Realtime Database
        if rtdb_available:
            try:
                safe_firebase_operation(
                    lambda: fb_db.reference('appointments').child(appointment_id).set(appointment)
                )
                logger.info(f"Appointment saved to Firebase: {appointment_id}")
            except Exception as e:
                logger.warning(f"Failed to save appointment to RTDB: {e}")
        
        return jsonify({
            'message': 'Appointment scheduled successfully',
            'appointment': appointment,
            'appointment_id': appointment_id
        })
    except Exception as e:
        logger.error(f"Error scheduling appointment: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/get_appointments', methods=['GET'])
def get_appointments():
    try:
        # Prefer RTDB if available
        if rtdb_available:
            snapshot = safe_firebase_operation(
                lambda: fb_db.reference('appointments').get(),
                {}
            )
            appointments_list = list(snapshot.values()) if isinstance(snapshot, dict) else []
        else:
            appointments_list = []
            with open('appointments.csv', 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    appointments_list.append(row)
        return jsonify({'appointments': appointments_list})
    except Exception as e:
        logger.error(f"Error getting appointments: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/cancel_appointment', methods=['POST'])
def cancel_appointment():
    try:
        data = request.json
        appointment_id = data.get('appointment_id')

        if not appointment_id:
            return jsonify({'error': 'Appointment ID is required'}), 400

        # Read all appointments from CSV (best-effort)
        appointments_list = []
        try:
            with open('appointments.csv', 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                appointments_list = list(reader)
        except FileNotFoundError:
            appointments_list = []

        appointment_row = None
        for row in appointments_list:
            if row.get('id') == appointment_id:
                row['status'] = 'cancelled'
                appointment_row = row
                break

        # Persist back CSV file if we loaded any
        if appointments_list:
            with open('appointments.csv', 'w', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(
                    f,
                    fieldnames=['id', 'title', 'time', 'notes', 'status', 'user_name', 'user_email', 'user_phone']
                )
                writer.writeheader()
                writer.writerows(appointments_list)

        # Update Firebase and fetch latest details
        fb_details = None
        if rtdb_available:
            try:
                # Read current data
                fb_details = safe_firebase_operation(
                    lambda: fb_db.reference('appointments').child(appointment_id).get(),
                    None
                )
                if fb_details is not None:
                    fb_details['status'] = 'cancelled'
                    safe_firebase_operation(
                        lambda: fb_db.reference('appointments').child(appointment_id).update({'status': 'cancelled'})
                    )
                    logger.info(f"Appointment cancelled in Firebase: {appointment_id}")
            except Exception as e:
                logger.warning(f"Failed to update appointment in RTDB: {e}")

        # Prefer Firebase details, else CSV row, else minimal
        result_appt = fb_details or appointment_row or {'id': appointment_id, 'status': 'cancelled'}

        return jsonify({
            'message': 'Appointment cancelled successfully',
            'appointment_id': appointment_id,
            'appointment': result_appt
        })

    except Exception as e:
        logger.error(f"Error cancelling appointment: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/voice', methods=['POST'])
def voice():
    """Handle incoming voice calls"""
    response = VoiceResponse()
    
    # Get the user's input from the call
    gather = Gather(input='speech', action='/handle-voice-input', method='POST')
    gather.say('Welcome to IM Solutions. How can I help you today?', voice='Polly.Amy')
    response.append(gather)
    
    # If the user doesn't say anything, repeat the prompt
    response.say('I didn\'t catch that. Please try again.', voice='Polly.Amy')
    response.redirect('/voice')
    
    return str(response)

@app.route('/handle-voice-input', methods=['POST'])
def handle_voice_input():
    """Process voice input and respond"""
    response = VoiceResponse()
    
    # Get the transcribed speech from the call
    speech_result = request.values.get('SpeechResult', '')
    call_sid = request.values.get('CallSid', '')
    
    if speech_result:
        # Get response from the chatbot
        bot_response = get_chatgpt_response(speech_result)
        
        # Store the conversation for summary
        if call_sid not in call_summaries:
            call_summaries[call_sid] = []
        call_summaries[call_sid].append({
            'user': speech_result,
            'bot': bot_response,
            'timestamp': datetime.now().isoformat()
        })
        
        # Convert the response to speech
        response.say(bot_response, voice='Polly.Amy')
        
        # Ask if there's anything else
        gather = Gather(input='speech', action='/handle-voice-input', method='POST')
        gather.say('Is there anything else I can help you with?', voice='Polly.Amy')
        response.append(gather)
    else:
        response.say('I didn\'t catch that. Please try again.', voice='Polly.Amy')
        response.redirect('/voice')
    
    return str(response)

@app.route('/call-completed', methods=['POST'])
def call_completed():
    """Handle call completion and save summary"""
    try:
        call_sid = request.values.get('CallSid')
        duration = request.values.get('CallDuration')
        phone_number = request.values.get('To')
        
        if call_sid in call_summaries:
            # Generate summary of the conversation
            conversation = call_summaries[call_sid]
            summary = "Call Summary:\n"
            for exchange in conversation:
                summary += f"User: {exchange['user']}\n"
                summary += f"Bot: {exchange['bot']}\n"
                summary += f"Time: {exchange['timestamp']}\n\n"
            
            # Save to Google Sheets
            save_call_summary(call_sid, phone_number, duration, summary)
            
            # Clean up
            del call_summaries[call_sid]
        
        return '', 200
    except Exception as e:
        logger.error(f"Error handling call completion: {str(e)}")
        return '', 500

@app.route('/initiate-call', methods=['POST'])
def initiate_call():
    try:
        # Get the user's phone number from the request
        data = request.json
        to_number = data.get('phone_number')
        
        if not to_number:
            return jsonify({
                'success': False,
                'message': 'Phone number is required'
            }), 400
            
        logger.info(f"Attempting to initiate call to {to_number} from {TWILIO_PHONE_NUMBER}")
        logger.info(f"Using Twilio credentials - Account SID: {TWILIO_ACCOUNT_SID[:5]}...")
        
        # Make the call using Twilio
        call = twilio_client.calls.create(
            to=to_number,
            from_=TWILIO_PHONE_NUMBER,
            url='https://437f-14-195-161-134.ngrok-free.app/voice',  # Updated ngrok URL
            status_callback='https://437f-14-195-161-134.ngrok-free.app/call-completed',  # Updated ngrok URL
            status_callback_event=['completed'],
            status_callback_method='POST'
        )
        
        logger.info(f"Call initiated successfully with SID: {call.sid}")
        return jsonify({
            'success': True,
            'message': 'Call initiated successfully',
            'call_sid': call.sid
        })
    except Exception as e:
        error_msg = f"Error initiating call: {str(e)}"
        logger.error(error_msg)
        logger.exception("Full traceback:")
        return jsonify({
            'success': False,
            'message': error_msg,
            'error_details': str(e)
        }), 500

@app.route('/test-sheets', methods=['GET'])
def test_sheets_connection():
    try:
        service = get_google_sheets_service()
        
        # Try to read the first row of the sheet
        result = service.spreadsheets().values().get(
            spreadsheetId=SPREADSHEET_ID,
            range='Calls!A1:E1'
        ).execute()
        
        # Try to write a test row
        test_values = [[
            datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'TEST_CALL_SID',
            'TEST_PHONE',
            '0',
            'Test connection successful'
        ]]
        
        body = {
            'values': test_values
        }
        
        write_result = service.spreadsheets().values().append(
            spreadsheetId=SPREADSHEET_ID,
            range=RANGE_NAME,
            valueInputOption='RAW',
            body=body
        ).execute()
        
        return jsonify({
            'success': True,
            'message': 'Google Sheets connection successful',
            'read_result': result.get('values', []),
            'write_result': write_result
        })
    except Exception as e:
        logger.error(f"Error testing Google Sheets connection: {str(e)}")
        return jsonify({
            'success': False,
            'message': f'Error: {str(e)}'
        }), 500

@app.route('/create_lead', methods=['POST'])
def create_lead():
    try:
        if not rtdb_available:
            return jsonify({'success': False, 'message': 'Leads storage is not configured (Realtime Database is unavailable).'}), 503

        data = request.json or {}
        name = data.get('name', '').strip()
        email = data.get('email', '').strip()
        phone = data.get('phone', '').strip()
        message = data.get('message', '').strip()

        if not name or not (email or phone):
            return jsonify({'success': False, 'message': 'Name and at least one contact (email or phone) are required.'}), 400

        lead_id = str(uuid.uuid4())
        now_ts = int(time.time() * 1000)
        lead_data = {
            'id': lead_id,
            'name': name,
            'email': email,
            'phone': phone,
            'message': message,
            'source': 'chatbot',
            'created_at': now_ts
        }

        safe_firebase_operation(
            lambda: fb_db.reference('leads').child(lead_id).set(lead_data)
        )

        return jsonify({'success': True, 'message': 'Lead submitted successfully', 'lead_id': lead_id})
    except Exception as e:
        logger.error(f"Error creating lead: {str(e)}")
        return jsonify({'success': False, 'message': str(e)}), 500

# Helper function for safe Firebase operations
def safe_firebase_operation(operation, default_value=None):
    """Safely execute Firebase operations with error handling"""
    if not rtdb_available:
        return default_value
    
    try:
        return operation()
    except Exception as e:
        logger.warning(f"Firebase operation failed: {e}")
        return default_value

@app.route('/dashboard', methods=['GET'])
@login_required
def dashboard():
    try:
        error_message = None
        leads = []
        appointments_view = []
        conversations = []
        users = []
        metrics = {
            'totalLeads': 0,
            'leadsToday': 0,
            'totalAppointments': 0,
            'upcomingAppointments': 0,
            'totalConversations': 0,
            'totalUsers': 0
        }
        leads_day_counts = defaultdict(int)
        appt_status_counts = Counter()

        if not rtdb_available:
            error_message = 'Realtime Database is not configured on the server. Upload credentials and restart the app.'
        else:
            # Load leads
            leads_snapshot = safe_firebase_operation(
                lambda: fb_db.reference('leads').get(),
                {}
            )
            
            for key, d in leads_snapshot.items():
                created_ms = d.get('created_at') or 0
                try:
                    created_dt = datetime.fromtimestamp(created_ms / 1000)
                    created_iso = created_dt.isoformat()
                    leads_day_counts[created_dt.strftime('%Y-%m-%d')] += 1
                except Exception:
                    created_dt = None
                    created_iso = str(created_ms)
                leads.append({
                    'id': d.get('id', key),
                    'name': d.get('name', ''),
                    'email': d.get('email', ''),
                    'phone': d.get('phone', ''),
                    'message': d.get('message', ''),
                    'source': d.get('source', ''),
                    'created_at': created_iso
                })

            # Load appointments
            appointments_snapshot = safe_firebase_operation(
                lambda: fb_db.reference('appointments').get(),
                {}
            )
            
            for key, d in appointments_snapshot.items():
                time_str = d.get('time', '')
                try:
                    time_dt = datetime.fromisoformat(time_str.replace('Z', '+00:00'))
                    time_iso = time_dt.isoformat()
                except Exception:
                    time_dt = None
                    time_iso = time_str
                status = (d.get('status') or 'pending').lower()
                
                # Extract user information properly
                user_data = d.get('user', {})
                if not user_data:
                    # Fallback to flat fields if user object doesn't exist
                    user_data = {
                        'name': d.get('user_name', ''),
                        'email': d.get('user_email', ''),
                        'phone': d.get('user_phone', ''),
                        'company': d.get('user_company', '')
                    }
                
                # Ensure user data has proper structure
                if isinstance(user_data, dict):
                    user_info = {
                        'name': user_data.get('name', 'Anonymous User'),
                        'email': user_data.get('email', ''),
                        'phone': user_data.get('phone', ''),
                        'company': user_data.get('company', '')
                    }
                else:
                    user_info = {
                        'name': 'Anonymous User',
                        'email': '',
                        'phone': '',
                        'company': ''
                    }
                
                # If user name is still empty, provide a meaningful default
                if not user_info['name'] or user_info['name'] == 'Anonymous':
                    user_info['name'] = 'Anonymous User'
                
                # Log the user info for debugging
                logger.debug(f"Appointment {d.get('id', key)} user info: {user_info}")
                
                appointments_view.append({
                    'id': d.get('id', key),
                    'title': d.get('title', ''),
                    'time': time_iso,
                    'notes': d.get('notes', ''),
                    'status': status,
                    'user': user_info
                })
                appt_status_counts[status] += 1
                try:
                    if status != 'cancelled' and time_dt and time_dt > datetime.utcnow():
                        metrics['upcomingAppointments'] += 1
                except Exception:
                    pass

            # Load conversations and extract user details
            conversations_snapshot = safe_firebase_operation(
                lambda: fb_db.reference('conversations').get(),
                {}
            )
            
            user_sessions = {}  # Track users by session_id
            
            for key, d in conversations_snapshot.items():
                timestamp_ms = d.get('timestamp') or 0
                try:
                    timestamp_iso = datetime.fromtimestamp(timestamp_ms / 1000).isoformat()
                except Exception:
                    timestamp_iso = str(timestamp_ms)
                
                user_details = d.get('user_details', {})
                session_id = d.get('session_id', 'default')
                
                conversations.append({
                    'id': d.get('id', key),
                    'user_message': d.get('user_message', ''),
                    'bot_response': d.get('bot_response', ''),
                    'timestamp': timestamp_iso,
                    'session_id': session_id,
                    'user_details': user_details
                })
                
                # Track unique users by session
                if session_id not in user_sessions:
                    user_sessions[session_id] = {
                        'name': user_details.get('name', 'Anonymous'),
                        'email': user_details.get('email', ''),
                        'phone': user_details.get('phone', ''),
                        'first_seen': timestamp_iso,
                        'last_seen': timestamp_iso,
                        'session_id': session_id,
                        'conversation_count': 1
                    }
                else:
                    user_sessions[session_id]['last_seen'] = timestamp_iso
                    user_sessions[session_id]['conversation_count'] += 1
            
            # Convert user sessions to list
            users = list(user_sessions.values())

            # Build a unified unique-user set from sessions and from 'users' node (chatbot form)
            unique_keys = set()
            def _key_from(u):
                for k in [u.get('email'), u.get('phone'), u.get('session_id')]:
                    if k:
                        return k
                return None

            for u in users:
                k = _key_from(u)
                if k:
                    unique_keys.add(k)

            # Pull users captured via chatbot form and merge
            try:
                form_users_snapshot = safe_firebase_operation(
                    lambda: fb_db.reference('users').get(),
                    {}
                )
                if isinstance(form_users_snapshot, dict) and form_users_snapshot:
                    for key2, u2 in form_users_snapshot.items():
                        k2 = None
                        for k in [u2.get('email'), u2.get('phone')]:
                            if k:
                                k2 = k
                                break
                        if k2:
                            unique_keys.add(k2)
                else:
                    # Fallback to local users_data.json to keep metrics in sync with table
                    try:
                        if os.path.exists('users_data.json'):
                            with open('users_data.json', 'r', encoding='utf-8') as f:
                                for line in f:
                                    if not line.strip():
                                        continue
                                    u2 = json.loads(line.strip())
                                    k2 = None
                                    for k in [u2.get('email'), u2.get('phone')]:
                                        if k:
                                            k2 = k
                                            break
                                    if k2:
                                        unique_keys.add(k2)
                    except Exception:
                        pass
            except Exception:
                pass

            metrics['totalUsers'] = len(unique_keys)

        try:
            leads.sort(key=lambda x: x.get('created_at') or '', reverse=True)
        except Exception:
            pass
        try:
            appointments_view.sort(key=lambda x: x.get('time') or '', reverse=True)
        except Exception:
            pass
        try:
            conversations.sort(key=lambda x: x.get('timestamp') or '', reverse=True)
        except Exception:
            pass

        # Metrics summary
        metrics['totalLeads'] = len(leads)
        metrics['totalAppointments'] = len(appointments_view)
        metrics['totalConversations'] = len(conversations)
        if metrics.get('totalUsers', 0) == 0:
            metrics['totalUsers'] = len(users)
        try:
            metrics['leadsToday'] = leads_day_counts.get(datetime.utcnow().strftime('%Y-%m-%d'), 0)
        except Exception:
            metrics['leadsToday'] = 0

        # Build charts data (use weekday labels)
        try:
            labels = []
            data = []
            today = datetime.utcnow().date()
            for i in range(6, -1, -1):
                day = today - timedelta(days=i)
                k = day.strftime('%Y-%m-%d')
                labels.append(day.strftime('%a'))
                data.append(leads_day_counts.get(k, 0))
            leads_chart_labels = labels
            leads_chart_data = data
        except Exception:
            leads_chart_labels = []
            leads_chart_data = []

        appt_status_labels = list(appt_status_counts.keys())
        appt_status_data = [appt_status_counts[k] for k in appt_status_labels]

        return render_template(
            'dashboard.html',
            leads=leads,
            appointments=appointments_view,
            conversations=conversations,
            users=users,
            error_message=error_message,
            metrics=metrics,
            leads_chart_labels=leads_chart_labels,
            leads_chart_data=leads_chart_data,
            appt_status_labels=appt_status_labels,
            appt_status_data=appt_status_data,
            rtdb_available=rtdb_available
        )
    except Exception as e:
        logger.error(f"Error loading dashboard: {str(e)}")
        return render_template('dashboard.html', 
            leads=[], 
            appointments=[], 
            conversations=[], 
            users=[], 
            error_message=str(e),
            metrics={
                'totalLeads': 0,
                'leadsToday': 0,
                'totalAppointments': 0,
                'upcomingAppointments': 0,
                'totalConversations': 0,
                'totalUsers': 0
            },
            leads_chart_labels=[],
            leads_chart_data=[],
            appt_status_labels=[],
            appt_status_data=[],
            rtdb_available=rtdb_available
        )

@app.route('/set_user_session', methods=['POST'])
def set_user_session():
    """Set user data in Flask session for appointment scheduling"""
    try:
        data = request.get_json()
        session['name'] = data.get('name', '')
        session['email'] = data.get('email', '')
        session['phone'] = data.get('phone', '')
        session['company'] = data.get('company', '')
        logger.info(f"User session updated: {session.get('name', 'Unknown')}")
        return jsonify({'success': True})
    except Exception as e:
        logger.error(f"Error setting user session: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/store_user_data', methods=['POST'])
def store_user_data():
    """Store user form data from chatbot"""
    try:
        data = request.get_json()
        name = data.get('name', '').strip()
        email = data.get('email', '').strip()
        phone = data.get('phone', '').strip()
        company = data.get('company', '').strip()
        
        if not name:
            return jsonify({'success': False, 'error': 'Name is required'}), 400
        
        # If incoming details differ from current session, rotate session_id to isolate conversations
        if (session.get('name') != name) or (session.get('email') != email) or (session.get('phone') != phone):
            session['session_id'] = f"session_{int(time.time())}_{random.randint(1000,9999)}"
        
        # Update server session for future messages
        session['name'] = name
        session['email'] = email
        session['phone'] = phone
        session['company'] = company
        if not session.get('session_id'):
            session['session_id'] = f"session_{int(time.time())}_{random.randint(1000,9999)}"
        
        # Create user data entry
        user_data = {
            'name': name,
            'email': email,
            'phone': phone,
            'company': company,
            'created_at': int(time.time() * 1000),  # Use timestamp in milliseconds
            'last_interaction': int(time.time() * 1000),
            'source': 'existing'
        }
        
        # Store in Firebase if available (no conversation backfill)
        if rtdb_available:
            try:
                # Store in users collection with source 'existing'
                users_ref = fb_db.reference('users')
                user_id = f"user_{int(time.time())}_{random.randint(1000, 9999)}"
                users_ref.child(user_id).set(user_data)
                
                # Also store in leads collection for dashboard
                leads_ref = fb_db.reference('leads')
                lead_id = f"lead_{int(time.time())}_{random.randint(1000, 9999)}"
                lead_data = {
                    'id': lead_id,
                    'name': name,
                    'email': email,
                    'phone': phone,
                    'company': company,
                    'message': "User registered via chatbot conversation",
                    'created_at': int(time.time() * 1000),
                    'source': 'existing'
                }
                leads_ref.child(lead_id).set(lead_data)
                
                logger.info(f"User data stored successfully: {name}")
                return jsonify({'success': True, 'user_id': user_id, 'lead_id': lead_id})
                
            except Exception as e:
                logger.error(f"Firebase error storing user data: {e}")
                # Fall back to local storage
                pass
        
        # Fallback: Store locally
        try:
            with open('users_data.json', 'r') as f:
                users = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            users = []
        
        # Check if user already exists
        existing_user = None
        for user in users:
            if (user.get('email') == email and email) or (user.get('phone') == phone and phone):
                existing_user = user
                break
        
        if existing_user:
            # Update existing user
            existing_user.update(user_data)
            existing_user['last_interaction'] = int(time.time() * 1000)
        else:
            # Add new user
            users.append(user_data)
        
        # Save to file
        with open('users_data.json', 'w') as f:
            json.dump(users, f, indent=2)
        
        logger.info(f"User data stored locally: {name}")
        return jsonify({'success': True, 'message': 'User data stored successfully'})
        
    except Exception as e:
        logger.error(f"Error storing user data: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/get_users_data')
def get_users_data():
    """Get all users data for dashboard"""
    try:
        users_data = []
        unique_keys = set()

        def add_user(u: dict):
            key = u.get('email') or u.get('phone') or u.get('session_id')
            if key and key not in unique_keys:
                unique_keys.add(key)
                users_data.append(u)

        # From conversations (chatbot users)
        if rtdb_available:
            try:
                convs = fb_db.reference('conversations').get() or {}
                if isinstance(convs, dict):
                    for _id, c in convs.items():
                        details = c.get('user_details') or {}
                        name = details.get('name') or 'Anonymous'
                        email = details.get('email') or ''
                        phone = details.get('phone') or ''
                        ts_ms = c.get('timestamp') or 0
                        add_user({
                            'name': name,
                            'email': email,
                            'phone': phone,
                            'company': '',
                            'timestamp': datetime.fromtimestamp(ts_ms/1000).isoformat() if ts_ms else '',
                            'source': 'chatbot',
                            'session_id': c.get('session_id', '')
                        })
            except Exception as e:
                logger.error(f"Failed to read conversations for users: {e}")

        # From users node (chatbot_form)
        if rtdb_available:
            try:
                users_ref = fb_db.reference('users')
                firebase_data = users_ref.get() or {}
                if isinstance(firebase_data, dict):
                    for key, value in firebase_data.items():
                        if isinstance(value, dict):
                            add_user({
                                'name': value.get('name') or 'Anonymous',
                                'email': value.get('email') or '',
                                'phone': value.get('phone') or '',
                                'company': value.get('company') or '',
                                'timestamp': value.get('timestamp') or value.get('created_at') or '',
                                'source': value.get('source') or 'chatbot_form',
                                'session_id': ''
                            })
            except Exception as e:
                logger.error(f"Failed to get users data from Firebase: {e}")
        
        # Local fallback
        if not users_data:
            try:
                if os.path.exists('users_data.json'):
                    with open('users_data.json', 'r') as f:
                        for line in f:
                            if line.strip():
                                user_data = json.loads(line.strip())
                                user_data['source'] = user_data.get('source') or 'chatbot_form'
                                add_user(user_data)
            except Exception as e:
                logger.error(f"Failed to read local users data: {e}")
        
        return jsonify({'users': users_data})
        
    except Exception as e:
        logger.error(f"Error getting users data: {e}")
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    # Create appointments directory if it doesn't exist
    os.makedirs('appointments', exist_ok=True)
    app.run(debug=True, port=5001) 