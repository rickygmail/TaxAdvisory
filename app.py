import os
from flask import Flask, render_template, request, redirect, url_for, flash
from dotenv import load_dotenv
from werkzeug.utils import secure_filename
import PyPDF2
import pytesseract
from PIL import Image
import re
import uuid
import psycopg2
from tax_calculator import calculate_old_regime, calculate_new_regime
from gemini_helper import get_gemini_followup_question, get_gemini_suggestion
import json

# Load environment variables from .env
load_dotenv()

UPLOAD_FOLDER = 'uploads'
ALLOWED_EXTENSIONS = {'pdf', 'jpg', 'jpeg', 'png', 'txt'}

app = Flask(__name__, template_folder='templates')
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.secret_key = 'supersecretkey'  # For flash messages

# Ensure uploads directory exists
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def extract_data_from_pdf(filepath):
    try:
        print(f"[PDF Extraction] Opening file: {filepath}")
        with open(filepath, 'rb') as f:
            print("[PDF Extraction] File opened successfully.")
            reader = PyPDF2.PdfReader(f)
            print(f"[PDF Extraction] Number of pages: {len(reader.pages)}")
            text = ''
            for i, page in enumerate(reader.pages):
                print(f"[PDF Extraction] Extracting text from page {i+1}...")
                page_text = page.extract_text()
                if page_text:
                    print(f"[PDF Extraction] Page {i+1} text length: {len(page_text)}")
                    text += page_text
                else:
                    print(f"[PDF Extraction] No text found on page {i+1}.")
            print(f"[PDF Extraction] Total extracted text length: {len(text)}")
        return text
    except Exception as e:
        print(f"[PDF Extraction] Error: {e}")
        return ''

def extract_data_from_image(filepath):
    try:
        img = Image.open(filepath)
        text = pytesseract.image_to_string(img)
        return text
    except Exception as e:
        return ''

def extract_data_from_txt(filepath):
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            return f.read()
    except Exception as e:
        return ''

def parse_financial_data(text):
    # Improved regex patterns and debug logging
    patterns = {
        'gross_salary': r'(?i)gross\s*salary\s*[:=]?\s*([\d,.]+)',
        'basic_salary': r'(?i)basic(\s*pay|\s*salary)?\s*[:=]?\s*([\d,.]+)',
        'hra_received': r'(?i)(hra(\s*received)?|house\s*rent\s*allowance)\s*[:=]?\s*([\d,.]+)',
        'rent_paid': r'(?i)rent\s*paid\s*[:=]?\s*([\d,.]+)',
        'deduction_80c': r'(?i)80c\s*(?:deduction|investment)?\s*[:=]?\s*([\d,.]+)',
        'deduction_80d': r'(?i)80d\s*(?:deduction|investment)?\s*[:=]?\s*([\d,.]+)',
        'standard_deduction': r'(?i)standard\s*deduction\s*[:=]?\s*([\d,.]+)',
        'professional_tax': r'(?i)professional\s*tax\s*[:=]?\s*([\d,.]+)',
        'tds': r'(?i)tds\s*[:=]?\s*([\d,.]+)'
    }
    data = {}
    for field, pattern in patterns.items():
        match = re.search(pattern, text)
        if match:
            # For patterns with multiple groups, get the last group (the number)
            value = match.groups()[-1].replace(',', '')
            print(f"[Mapping] {field}: matched value '{value}' with pattern '{pattern}'")
            data[field] = value
        else:
            print(f"[Mapping] {field}: no match with pattern '{pattern}'")
            data[field] = ''
    return data

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/upload', methods=['GET', 'POST'])
def upload():
    if request.method == 'POST':
        if 'file' not in request.files:
            return render_template('form.html', error='No file part')
        file = request.files['file']
        if file.filename == '':
            return render_template('form.html', error='No selected file')
        if file and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(filepath)
            # Extract data
            ext = filename.rsplit('.', 1)[1].lower()
            if ext == 'pdf':
                text = extract_data_from_pdf(filepath)
            elif ext in ['jpg', 'jpeg', 'png']:
                text = extract_data_from_image(filepath)
            elif ext == 'txt':
                text = extract_data_from_txt(filepath)
            else:
                text = ''
            data = parse_financial_data(text)
            # Set default values as 0 for all fields
            for field in data:
                if data[field] == '' or data[field] is None:
                    data[field] = '0'
            os.remove(filepath)  # Delete after extraction
            return render_template('form.html', data=data)
        else:
            return render_template('form.html', error='Unsupported file type')
    return render_template('form.html')

@app.route('/review', methods=['POST'])
def review():
    data = {field: request.form.get(field, '') for field in [
        'gross_salary', 'basic_salary', 'hra_received', 'rent_paid',
        'deduction_80c', 'deduction_80d', 'standard_deduction',
        'professional_tax', 'tds']}
    # Set default values for blank fields
    for field in data:
        if data[field] == '' or data[field] is None:
            if field == 'standard_deduction':
                data[field] = '50000'
            else:
                data[field] = '0'
    selected_regime = request.form.get('regime', 'new')
    # Calculate tax for both regimes
    old_tax, old_taxable_income, old_deductions = calculate_old_regime(data)
    new_tax, new_taxable_income, new_deduction = calculate_new_regime(data)
    best_regime = 'old' if old_tax < new_tax else 'new'
    # Save to DB
    session_id = str(uuid.uuid4())
    try:
        DB_URL = os.getenv('DB_URL')
        conn = psycopg2.connect(DB_URL)
        cur = conn.cursor()
        # Save user data
        cur.execute('''
            INSERT INTO "UserFinancials" (
                session_id, gross_salary, basic_salary, hra_received, rent_paid,
                deduction_80c, deduction_80d, standard_deduction, professional_tax, tds
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ''', [session_id, data['gross_salary'] or None, data['basic_salary'] or None, data['hra_received'] or None, data['rent_paid'] or None, data['deduction_80c'] or None, data['deduction_80d'] or None, data['standard_deduction'] or None, data['professional_tax'] or None, data['tds'] or None])
        # Save tax comparison
        cur.execute('''
            CREATE TABLE IF NOT EXISTS "TaxComparison" (
                session_id UUID PRIMARY KEY,
                old_tax NUMERIC(15,2),
                new_tax NUMERIC(15,2),
                best_regime VARCHAR(10),
                selected_regime VARCHAR(10),
                created_at TIMESTAMPTZ DEFAULT NOW()
            );
        ''')
        cur.execute('''
            INSERT INTO "TaxComparison" (
                session_id, old_tax, new_tax, best_regime, selected_regime
            ) VALUES (%s, %s, %s, %s, %s)
        ''', [session_id, old_tax, new_tax, best_regime, selected_regime])
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        print(f"[DB] Error saving data: {e}")
        flash('Error saving data to database.')
    # After saving, show Gemini follow-up question
    ai_question = get_gemini_followup_question(data)
    return render_template('ask.html', ai_question=ai_question, session_id=session_id)

@app.route('/advisor', methods=['POST'])
def advisor():
    session_id = request.form.get('session_id')
    user_answer = request.form.get('user_answer')
    # Retrieve user data from DB
    DB_URL = os.getenv('DB_URL')
    user_data = {}
    try:
        conn = psycopg2.connect(DB_URL)
        cur = conn.cursor()
        cur.execute('SELECT gross_salary, basic_salary, hra_received, rent_paid, deduction_80c, deduction_80d, standard_deduction, professional_tax, tds FROM "UserFinancials" WHERE session_id = %s', (session_id,))
        row = cur.fetchone()
        if row:
            keys = ['gross_salary', 'basic_salary', 'hra_received', 'rent_paid', 'deduction_80c', 'deduction_80d', 'standard_deduction', 'professional_tax', 'tds']
            user_data = dict(zip(keys, row))
        cur.close()
        conn.close()
    except Exception as e:
        print(f"[DB] Error fetching user data: {e}")
    # Get Gemini suggestion
    ai_suggestion = get_gemini_suggestion(user_data, user_answer)
    # Log conversation
    log_entry = {
        'session_id': session_id,
        'user_data': user_data,
        'ai_question': get_gemini_followup_question(user_data),
        'user_answer': user_answer,
        'ai_suggestion': ai_suggestion
    }
    try:
        log_path = 'ai_conversation_log.json'
        if os.path.exists(log_path):
            with open(log_path, 'r', encoding='utf-8') as f:
                logs = json.load(f)
        else:
            logs = []
        logs.append(log_entry)
        with open(log_path, 'w', encoding='utf-8') as f:
            json.dump(logs, f, indent=2)
    except Exception as e:
        print(f"[AI Log] Error: {e}")
    ai_question = get_gemini_followup_question(user_data)
    return render_template('ask.html', ai_question=ai_question, ai_suggestion=ai_suggestion, session_id=session_id)

if __name__ == '__main__':
    app.run(debug=True) 