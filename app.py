import os
import base64
import logging
import traceback
from io import BytesIO
from PIL import Image
from flask import Flask, render_template, request, redirect, url_for, session, jsonify
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
import google.generativeai as genai
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

app = Flask(__name__)

# Use SQLite database
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///app.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.secret_key = os.getenv('FLASK_SECRET_KEY') or 'your-secret-key'
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['ALLOWED_EXTENSIONS'] = {'png', 'jpg', 'jpeg', 'gif'}

# Ensure upload folder exists
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

db = SQLAlchemy(app)

# User model
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

# Allowed file check
def allowed_file(filename):
    return '.' in filename and \
        filename.rsplit('.', 1)[1].lower() in app.config['ALLOWED_EXTENSIONS']

# Routes
@app.route('/')
def home():
    return render_template('index.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        user = User.query.filter_by(username=username).first()
        if user and user.check_password(password):
            session['user'] = username
            return redirect(url_for('dashboard'))
        else:
            return "Invalid credentials", 401
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        if User.query.filter_by(username=username).first():
            return "User already exists", 400
        new_user = User(username=username)
        new_user.set_password(password)
        db.session.add(new_user)
        db.session.commit()
        return redirect(url_for('login'))
    return render_template('register.html')

@app.route('/dashboard')
def dashboard():
    if 'user' not in session:
        return redirect(url_for('login'))
    return render_template('dashboard.html', user=session['user'])

@app.route('/logout')
def logout():
    session.pop('user', None)
    return redirect(url_for('home'))

# Gemini API route
@app.route('/api/gemini', methods=['POST'])
def gemini_api():
    if 'user' not in session:
        return jsonify({'error': 'لطفاً ابتدا وارد حساب کاربری خود شوید.'}), 401

    google_gemini_api_key = os.getenv("google_gemini_api_key")
    if not google_gemini_api_key:
        return jsonify({'error': 'خطای سرور: تنظیمات API درست نیست.'}), 500

    image_file = request.files.get('imageInput')
    if not image_file:
        return jsonify({'error': 'لطفاً یک تصویر آپلود کنید.'}), 400

    allowed_types = ['image/png', 'image/jpeg']
    max_size = 5 * 1024 * 1024  # 5MB

    if image_file.mimetype not in allowed_types:
        return jsonify({'error': 'فقط تصاویر PNG و JPEG پشتیبانی می‌شوند.'}), 400
    if len(image_file.read()) > max_size:
        return jsonify({'error': 'حجم تصویر نباید بیشتر از ۵ مگابایت باشد.'}), 400
    image_file.seek(0)

    static_prompt = """
    تصور کن که تو یک مهندس عمران با ۲۰ سال تجربه در زمینه بتن هستی.
    مشکل بتن تو این عکس چیه؟ چی باعث این مشکل شده؟
    به فارسی و با زبانی ساده و حرفه‌ای توضیح بده.
    پاسخ رو کوتاه و مفید نگه دار، حداکثر ۳-۴ جمله، و فقط مشکل، دلیل، و یک راهکار عملی ذکر کن.
    """

    try:
        img = Image.open(image_file.stream)
        if img.format not in ['PNG', 'JPEG']:
            return jsonify({'error': 'فرمت تصویر پشتیبانی نمی‌شود.'}), 400
        buffered = BytesIO()
        img = img.convert("RGB")
        img.save(buffered, format="PNG")
        img_bytes = buffered.getvalue()

        contents = [
            {"text": static_prompt},
            {"inline_data": {
                "data": base64.b64encode(img_bytes).decode('utf-8'),
                "mime_type": "image/png"
            }}
        ]

        genai.configure(api_key=google_gemini_api_key)
        model = genai.GenerativeModel('gemini-1.5-flash')
        response = model.generate_content(contents)
        response.resolve()

        if not response.text or response.text.strip() == '':
            return jsonify({'response': 'نمی‌تونم مشکل بتن رو از این تصویر تشخیص بدم. لطفاً تصویر واضح‌تری آپلود کنید.'})

        return jsonify({'response': response.text})

    except genai.exceptions.GenerationError:
        logging.error("Gemini API error", exc_info=True)
        return jsonify({'error': 'خطایی در تحلیل تصویر پیش اومد. لطفاً دوباره امتحان کنید.'}), 500
    except Exception:
        logging.error("Error processing request", exc_info=True)
        return jsonify({'error': 'یه مشکل فنی پیش اومده. لطفاً دوباره تلاش کنید.'}), 500

# Run the app
if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=True)
