import os
import json
import secrets
import bcrypt
import re
from datetime import datetime, timedelta
from flask import Flask, request, jsonify, session, make_response, send_file
from flask_sqlalchemy import SQLAlchemy
from flask_cors import CORS
from dotenv import load_dotenv
from functools import wraps
import random
import csv
from io import BytesIO, StringIO
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.pdfgen import canvas

load_dotenv()

app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', secrets.token_hex(32))
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///adp_system.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
CORS(app, supports_credentials=True)
db = SQLAlchemy(app)

# ============= DATABASE MODELS =============
class Admin(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(128), nullable=False)
    full_name = db.Column(db.String(200))
    role = db.Column(db.String(50), default='super_admin')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Employee(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    employee_id = db.Column(db.String(20), unique=True)
    user_id = db.Column(db.String(50), unique=True)
    password_hash = db.Column(db.String(128))
    full_name = db.Column(db.String(200), nullable=False)
    email = db.Column(db.String(120))
    phone = db.Column(db.String(20))
    address = db.Column(db.Text)
    city = db.Column(db.String(100))
    state = db.Column(db.String(50))
    zip_code = db.Column(db.String(20))
    ssn_last4 = db.Column(db.String(4))
    hire_date = db.Column(db.String(20))
    pay_rate = db.Column(db.Float)
    pay_type = db.Column(db.String(20), default='hourly')
    filing_status = db.Column(db.String(20), default='single')
    direct_deposit_bank = db.Column(db.String(100))
    direct_deposit_account = db.Column(db.String(50))
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class PayrollRun(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    employee_id = db.Column(db.Integer, db.ForeignKey('employee.id'))
    pay_period_start = db.Column(db.String(20))
    pay_period_end = db.Column(db.String(20))
    pay_date = db.Column(db.String(20))
    check_number = db.Column(db.String(20))
    hours_worked = db.Column(db.Float, default=80.0)
    overtime_hours = db.Column(db.Float, default=0)
    regular_pay = db.Column(db.Float)
    overtime_pay = db.Column(db.Float)
    gross_pay = db.Column(db.Float)
    federal_tax = db.Column(db.Float)
    social_security = db.Column(db.Float)
    medicare = db.Column(db.Float)
    state_tax = db.Column(db.Float, default=0.0)
    total_deductions = db.Column(db.Float)
    net_pay = db.Column(db.Float)
    ytd_gross = db.Column(db.Float)
    ytd_federal = db.Column(db.Float)
    ytd_ss = db.Column(db.Float)
    ytd_medicare = db.Column(db.Float)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class PayStub(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    payroll_id = db.Column(db.Integer, db.ForeignKey('payroll_run.id'))
    employee_id = db.Column(db.Integer, db.ForeignKey('employee.id'))
    stub_number = db.Column(db.String(50), unique=True)
    pdf_data = db.Column(db.LargeBinary)
    download_count = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class CompanyInfo(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    company_name = db.Column(db.String(200), default='U.S. TITLE & ESCROW INC')
    company_address = db.Column(db.Text, default='2715 E Oakland Park Blvd, Suite 300, Fort Lauderdale, FL 33306')
    company_phone = db.Column(db.String(20), default='(954) 555-0123')
    company_email = db.Column(db.String(120), default='payroll@ustitleescrow.com')
    company_ein = db.Column(db.String(50), default='65-0551000')
    bank_name = db.Column(db.String(100), default='SOUTH STATE BANK')
    routing_number = db.Column(db.String(20), default='063114030')
    account_number = db.Column(db.String(50), default='1510017575')
    updated_at = db.Column(db.DateTime, default=datetime.utcnow)

with app.app_context():
    db.create_all()
    
    # Create default admin
    if not Admin.query.first():
        default_password = bcrypt.hashpw("Admin123!".encode(), bcrypt.gensalt())
        default_admin = Admin(
            username="admin",
            email="admin@ustitleescrow.com",
            password_hash=default_password,
            full_name="Andrew Penn",
            role="super_admin"
        )
        db.session.add(default_admin)
        db.session.commit()
    
    # Create default company info
    if not CompanyInfo.query.first():
        default_company = CompanyInfo()
        db.session.add(default_company)
        db.session.commit()

# ============= HELPER FUNCTIONS =============
def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('authenticated'):
            return jsonify({'error': 'Please login first'}), 401
        return f(*args, **kwargs)
    return decorated

def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('is_admin'):
            return jsonify({'error': 'Admin access required'}), 403
        return f(*args, **kwargs)
    return decorated

def generate_employee_id():
    return f"EMP-{datetime.now().strftime('%Y')}-{random.randint(1000, 9999)}"

def generate_user_id(full_name):
    name_part = full_name.lower().replace(' ', '.')[:15]
    return f"{name_part}{random.randint(100, 999)}"

def generate_stub_number():
    return f"ADP-{datetime.now().strftime('%Y%m%d')}-{random.randint(1000, 9999)}"

def generate_check_number():
    return f"{datetime.now().strftime('%y%m%d')}{random.randint(1000, 9999)}"

def calculate_federal_tax(gross_pay, filing_status):
    if filing_status == 'single':
        if gross_pay <= 459: return 0
        elif gross_pay <= 1610: return (gross_pay - 459) * 0.10
        elif gross_pay <= 3830: return 115.10 + (gross_pay - 1610) * 0.12
        elif gross_pay <= 8970: return 381.50 + (gross_pay - 3830) * 0.22
        else: return 1504.30 + (gross_pay - 8970) * 0.24
    else:
        if gross_pay <= 1072: return 0
        elif gross_pay <= 3212: return (gross_pay - 1072) * 0.10
        elif gross_pay <= 7662: return 214.00 + (gross_pay - 3212) * 0.12
        elif gross_pay <= 17940: return 748.00 + (gross_pay - 7662) * 0.22
        else: return 3009.16 + (gross_pay - 17940) * 0.24

def calculate_social_security(gross_pay, ytd_gross=0):
    wage_base = 184500
    if ytd_gross + gross_pay > wage_base:
        taxable = max(0, wage_base - ytd_gross)
        return round(taxable * 0.062, 2)
    return round(gross_pay * 0.062, 2)

def calculate_medicare(gross_pay):
    return round(gross_pay * 0.0145, 2)

def create_paystub_pdf(payroll, employee, company):
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter, topMargin=0.5*inch, bottomMargin=0.5*inch)
    styles = getSampleStyleSheet()
    elements = []
    
    # Custom styles
    title_style = ParagraphStyle('TitleStyle', parent=styles['Heading1'], fontSize=18, textColor=colors.HexColor('#003057'), alignment=1)
    header_style = ParagraphStyle('HeaderStyle', parent=styles['Normal'], fontSize=10, textColor=colors.white, backColor=colors.HexColor('#003057'), alignment=1)
    
    # Header with ADP style
    elements.append(Paragraph("ADP", title_style))
    elements.append(Paragraph("Automatic Data Processing | Payroll Services", styles['Normal']))
    elements.append(Spacer(1, 0.2*inch))
    
    # Company info
    company_info = [
        [Paragraph(f"<b>{company.company_name}</b>", styles['Normal'])],
        [Paragraph(company.company_address, styles['Normal'])],
        [Paragraph(f"Phone: {company.company_phone} | EIN: {company.company_ein}", styles['Normal'])]
    ]
    company_table = Table(company_info, colWidths=[6.5*inch])
    company_table.setStyle(TableStyle([('ALIGN', (0,0), (-1,-1), 'CENTER'), ('FONTSIZE', (0,0), (-1,-1), 9)]))
    elements.append(company_table)
    elements.append(Spacer(1, 0.2*inch))
    
    # Employee info
    emp_info = [
        [Paragraph(f"<b>EMPLOYEE INFORMATION</b>", styles['Normal'])],
        [f"Name: {employee.full_name}                    Employee ID: {employee.employee_id}"],
        [f"User ID: {employee.user_id}                    SSN: XXX-XX-{employee.ssn_last4}"],
        [f"Pay Period: {payroll.pay_period_start} - {payroll.pay_period_end}                    Pay Date: {payroll.pay_date}"],
        [f"Check Number: {payroll.check_number}                    Pay Frequency: Bi-Weekly"]
    ]
    emp_table = Table(emp_info, colWidths=[6.5*inch])
    emp_table.setStyle(TableStyle([('FONTSIZE', (0,0), (-1,-1), 9), ('BACKGROUND', (0,0), (0,0), colors.HexColor('#e8e8e8'))]))
    elements.append(emp_table)
    elements.append(Spacer(1, 0.2*inch))
    
    # Earnings table
    earnings_data = [
        ['<b>EARNINGS</b>', '<b>Hours</b>', '<b>Rate</b>', '<b>Current</b>', '<b>YTD</b>'],
        ['Regular Pay', f"{payroll.hours_worked}", f"${employee.pay_rate:.2f}", f"${payroll.regular_pay:.2f}", "-"],
    ]
    if payroll.overtime_hours > 0:
        earnings_data.append(['Overtime', f"{payroll.overtime_hours}", f"${employee.pay_rate * 1.5:.2f}", f"${payroll.overtime_pay:.2f}", "-"])
    earnings_data.append(['<b>GROSS PAY</b>', '', '', f"<b>${payroll.gross_pay:.2f}</b>", f"<b>${payroll.ytd_gross:.2f}</b>"])
    
    earnings_table = Table(earnings_data, colWidths=[2.5*inch, 1*inch, 1*inch, 1.5*inch, 1.5*inch])
    earnings_table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#e8e8e8')),
        ('ALIGN', (1,1), (-1,-1), 'RIGHT'),
        ('FONTSIZE', (0,0), (-1,-1), 9),
        ('GRID', (0,0), (-1,-1), 0.5, colors.grey)
    ]))
    elements.append(earnings_table)
    elements.append(Spacer(1, 0.1*inch))
    
    # Deductions table
    deductions_data = [
        ['<b>DEDUCTIONS</b>', '<b>Rate</b>', '<b>Current</b>', '<b>YTD</b>'],
        ['Federal Income Tax', f"{calculate_federal_tax(payroll.gross_pay, employee.filing_status) / payroll.gross_pay * 100:.1f}%", f"${payroll.federal_tax:.2f}", f"${payroll.ytd_federal:.2f}"],
        ['Social Security', '6.2%', f"${payroll.social_security:.2f}", f"${payroll.ytd_ss:.2f}"],
        ['Medicare', '1.45%', f"${payroll.medicare:.2f}", f"${payroll.ytd_medicare:.2f}"],
        ['Florida State Tax', '0.0%', '$0.00', '$0.00'],
        ['<b>TOTAL DEDUCTIONS</b>', '', f"<b>${payroll.total_deductions:.2f}</b>", f"<b>${payroll.ytd_federal + payroll.ytd_ss + payroll.ytd_medicare:.2f}</b>"]
    ]
    deductions_table = Table(deductions_data, colWidths=[2.5*inch, 1.5*inch, 1.5*inch, 1.5*inch])
    deductions_table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#e8e8e8')),
        ('ALIGN', (1,1), (-1,-1), 'RIGHT'),
        ('FONTSIZE', (0,0), (-1,-1), 9),
        ('GRID', (0,0), (-1,-1), 0.5, colors.grey)
    ]))
    elements.append(deductions_table)
    elements.append(Spacer(1, 0.2*inch))
    
    # Net Pay box
    net_pay_data = [
        [f"<b>NET PAY</b>", f"<b>${payroll.net_pay:.2f}</b>"],
        [f"Direct Deposit: {employee.direct_deposit_bank or 'Check'}", ""]
    ]
    net_table = Table(net_pay_data, colWidths=[3*inch, 3*inch])
    net_table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,-1), colors.HexColor('#003057')),
        ('TEXTCOLOR', (0,0), (-1,-1), colors.white),
        ('FONTSIZE', (0,0), (-1,-1), 12),
        ('ALIGN', (0,0), (-1,-1), 'CENTER')
    ]))
    elements.append(net_table)
    elements.append(Spacer(1, 0.2*inch))
    
    # MICR line
    micr_line = f"⑆{company.routing_number}⑆{company.account_number[-4:]}⑆{payroll.check_number}⑆"
    elements.append(Paragraph(f"<font face='Courier' size='10'>{micr_line}</font>", styles['Normal']))
    elements.append(Spacer(1, 0.1*inch))
    
    # Footer
    elements.append(Paragraph(f"Stub ID: {generate_stub_number()} | Generated: {datetime.now().strftime('%m/%d/%Y %H:%M:%S')}", styles['Normal']))
    elements.append(Paragraph("This is an official ADP Pay Statement. For verification, contact payroll@ustitleescrow.com", styles['Normal']))
    
    doc.build(elements)
    buffer.seek(0)
    return buffer

# ============= AUTHENTICATION ENDPOINTS =============
@app.route('/api/auth/admin/login', methods=['POST'])
def admin_login():
    try:
        data = request.json
        admin = Admin.query.filter_by(username=data['username']).first()
        if not admin:
            admin = Admin.query.filter_by(email=data['username']).first()
        if not admin:
            return jsonify({'error': 'Invalid credentials'}), 401
        if not bcrypt.checkpw(data['password'].encode(), admin.password_hash):
            return jsonify({'error': 'Invalid credentials'}), 401
        session.permanent = True
        session['admin_id'] = admin.id
        session['is_admin'] = True
        session['authenticated'] = True
        return jsonify({'success': True, 'admin': {'username': admin.username, 'full_name': admin.full_name}})
    except Exception as e:
        return jsonify({'error': str(e)}), 400

@app.route('/api/auth/employee/login', methods=['POST'])
def employee_login():
    try:
        data = request.json
        employee = Employee.query.filter_by(user_id=data['user_id']).first()
        if not employee:
            return jsonify({'error': 'Invalid User ID'}), 401
        if not employee.password_hash:
            return jsonify({'error': 'Password not set. Contact admin.'}), 401
        if not bcrypt.checkpw(data['password'].encode(), employee.password_hash):
            return jsonify({'error': 'Invalid password'}), 401
        if not employee.is_active:
            return jsonify({'error': 'Account inactive'}), 403
        session.permanent = True
        session['employee_id'] = employee.id
        session['authenticated'] = True
        return jsonify({'success': True, 'employee': {'user_id': employee.user_id, 'full_name': employee.full_name}})
    except Exception as e:
        return jsonify({'error': str(e)}), 400

@app.route('/api/auth/logout', methods=['POST'])
def logout():
    session.clear()
    return jsonify({'success': True})

@app.route('/api/auth/me', methods=['GET'])
def get_current_user():
    try:
        if session.get('is_admin'):
            admin = Admin.query.get(session['admin_id'])
            return jsonify({'user': {'type': 'admin', 'username': admin.username, 'full_name': admin.full_name}})
        elif session.get('employee_id'):
            employee = Employee.query.get(session['employee_id'])
            return jsonify({'user': {'type': 'employee', 'user_id': employee.user_id, 'full_name': employee.full_name}})
        return jsonify({'error': 'Not logged in'}), 401
    except Exception as e:
        return jsonify({'error': str(e)}), 400

# ============= ADMIN ENDPOINTS =============
@app.route('/api/admin/employees', methods=['GET'])
@admin_required
def get_employees():
    employees = Employee.query.all()
    return jsonify({'employees': [{
        'id': e.id, 'employee_id': e.employee_id, 'user_id': e.user_id,
        'full_name': e.full_name, 'email': e.email, 'phone': e.phone,
        'pay_rate': e.pay_rate, 'filing_status': e.filing_status,
        'is_active': e.is_active, 'hire_date': e.hire_date,
        'direct_deposit_bank': e.direct_deposit_bank
    } for e in employees]})

@app.route('/api/admin/employees', methods=['POST'])
@admin_required
def add_employee():
    try:
        data = request.json
        employee_id = generate_employee_id()
        user_id = generate_user_id(data['full_name'])
        default_password = bcrypt.hashpw(data.get('password', 'Welcome123!').encode(), bcrypt.gensalt())
        
        employee = Employee(
            employee_id=employee_id, user_id=user_id, password_hash=default_password,
            full_name=data['full_name'], email=data.get('email', ''), phone=data.get('phone', ''),
            address=data.get('address', ''), city=data.get('city', ''), state=data.get('state', 'FL'),
            zip_code=data.get('zip_code', ''), ssn_last4=data.get('ssn_last4', ''),
            hire_date=data.get('hire_date', datetime.now().strftime('%m/%d/%Y')),
            pay_rate=data['pay_rate'], filing_status=data.get('filing_status', 'single'),
            direct_deposit_bank=data.get('direct_deposit_bank', ''),
            direct_deposit_account=data.get('direct_deposit_account', '')
        )
        db.session.add(employee)
        db.session.commit()
        return jsonify({'success': True, 'employee_id': employee_id, 'user_id': user_id, 'default_password': data.get('password', 'Welcome123!')})
    except Exception as e:
        return jsonify({'error': str(e)}), 400

@app.route('/api/admin/payroll/generate', methods=['POST'])
@admin_required
def generate_payroll():
    try:
        data = request.json
        employee = Employee.query.get(data['employee_id'])
        if not employee:
            return jsonify({'error': 'Employee not found'}), 404
        
        pay_period_end = datetime.now()
        pay_period_start = pay_period_end - timedelta(days=14)
        
        hours = data.get('hours', 80)
        overtime = data.get('overtime', 0)
        
        regular_pay = hours * employee.pay_rate
        overtime_pay = overtime * employee.pay_rate * 1.5
        gross_pay = regular_pay + overtime_pay
        
        previous_runs = PayrollRun.query.filter_by(employee_id=employee.id).all()
        ytd_gross = sum(r.gross_pay for r in previous_runs) + gross_pay
        
        federal_tax = calculate_federal_tax(gross_pay, employee.filing_status)
        social_security = calculate_social_security(gross_pay, ytd_gross - gross_pay)
        medicare = calculate_medicare(gross_pay)
        total_deductions = federal_tax + social_security + medicare
        net_pay = gross_pay - total_deductions
        check_number = generate_check_number()
        
        payroll = PayrollRun(
            employee_id=employee.id,
            pay_period_start=pay_period_start.strftime('%m/%d/%Y'),
            pay_period_end=pay_period_end.strftime('%m/%d/%Y'),
            pay_date=datetime.now().strftime('%m/%d/%Y'),
            check_number=check_number,
            hours_worked=hours, overtime_hours=overtime,
            regular_pay=regular_pay, overtime_pay=overtime_pay, gross_pay=gross_pay,
            federal_tax=federal_tax, social_security=social_security, medicare=medicare,
            total_deductions=total_deductions, net_pay=net_pay,
            ytd_gross=ytd_gross,
            ytd_federal=sum(r.federal_tax for r in previous_runs) + federal_tax,
            ytd_ss=sum(r.social_security for r in previous_runs) + social_security,
            ytd_medicare=sum(r.medicare for r in previous_runs) + medicare
        )
        db.session.add(payroll)
        db.session.commit()
        
        # Generate PDF
        company = CompanyInfo.query.first()
        pdf_buffer = create_paystub_pdf(payroll, employee, company)
        
        stub_number = generate_stub_number()
        pay_stub = PayStub(
            payroll_id=payroll.id, employee_id=employee.id,
            stub_number=stub_number, pdf_data=pdf_buffer.getvalue()
        )
        db.session.add(pay_stub)
        db.session.commit()
        
        return jsonify({'success': True, 'payroll_id': payroll.id, 'stub_number': stub_number,
                       'gross_pay': gross_pay, 'net_pay': net_pay, 'check_number': check_number})
    except Exception as e:
        return jsonify({'error': str(e)}), 400

@app.route('/api/payroll/stubs', methods=['GET'])
@login_required
def get_stubs():
    try:
        if session.get('is_admin'):
            stubs = PayStub.query.order_by(PayStub.created_at.desc()).all()
        else:
            employee = Employee.query.get(session['employee_id'])
            stubs = PayStub.query.filter_by(employee_id=employee.id).order_by(PayStub.created_at.desc()).all()
        
        result = []
        for stub in stubs:
            payroll = PayrollRun.query.get(stub.payroll_id)
            employee = Employee.query.get(stub.employee_id)
            result.append({
                'id': stub.id, 'stub_number': stub.stub_number, 'employee_name': employee.full_name,
                'pay_date': payroll.pay_date, 'gross_pay': payroll.gross_pay, 'net_pay': payroll.net_pay,
                'download_count': stub.download_count
            })
        return jsonify({'stubs': result})
    except Exception as e:
        return jsonify({'error': str(e)}), 400

@app.route('/api/payroll/stub/<int:stub_id>/download', methods=['GET'])
@login_required
def download_stub(stub_id):
    try:
        stub = PayStub.query.get(stub_id)
        if not stub:
            return jsonify({'error': 'Stub not found'}), 404
        
        # Check access
        if not session.get('is_admin') and stub.employee_id != session.get('employee_id'):
            return jsonify({'error': 'Access denied'}), 403
        
        stub.download_count += 1
        db.session.commit()
        
        return send_file(
            BytesIO(stub.pdf_data),
            mimetype='application/pdf',
            as_attachment=True,
            download_name=f"ADP_PayStub_{stub.stub_number}.pdf"
        )
    except Exception as e:
        return jsonify({'error': str(e)}), 400

@app.route('/api/company/info', methods=['GET'])
def get_company_info():
    company = CompanyInfo.query.first()
    return jsonify({
        'company_name': company.company_name, 'company_address': company.company_address,
        'company_phone': company.company_phone, 'company_email': company.company_email,
        'bank_name': company.bank_name, 'routing_number': company.routing_number
    })

# ============= FRONTEND =============
@app.route('/')
def home():
    return '<h1>ADP Payroll System</h1><p><a href="/login.html">Employee Login</a> | <a href="/admin.html">Admin Login</a></p>'

@app.route('/login.html')
def login_page():
    return '''
<!DOCTYPE html>
<html>
<head>
    <title>ADP Employee Login</title>
    <style>
        *{margin:0;padding:0;box-sizing:border-box;}
        body{font-family: Arial, sans-serif; background: #003057; min-height: 100vh; display: flex; justify-content: center; align-items: center;}
        .container{background: white; padding: 40px; border-radius: 12px; width: 400px; text-align: center;}
        .logo{color: #003057; font-size: 32px; font-weight: bold; margin-bottom: 10px;}
        input{width: 100%; padding: 12px; margin: 10px 0; border: 1px solid #ddd; border-radius: 6px;}
        button{width: 100%; padding: 12px; background: #003057; color: white; border: none; border-radius: 6px; cursor: pointer; font-size: 16px;}
        .error{color: red; margin-top: 10px;}
        .switch{margin-top: 20px; font-size: 12px;}
        a{color: #003057; text-decoration: none;}
    </style>
</head>
<body>
<div class="container">
    <div class="logo">ADP</div>
    <h3>Employee Login</h3>
    <input type="text" id="userId" placeholder="User ID">
    <input type="password" id="password" placeholder="Password">
    <button onclick="login()">Sign In</button>
    <div id="errorMsg" class="error"></div>
    <div class="switch"><a href="/admin.html">Admin Login</a></div>
</div>
<script>
async function login(){
    const userId = document.getElementById('userId').value;
    const password = document.getElementById('password').value;
    const res = await fetch('/api/auth/employee/login', {
        method: 'POST', headers: {'Content-Type': 'application/json'}, credentials: 'include',
        body: JSON.stringify({user_id: userId, password: password})
    });
    const data = await res.json();
    if(data.success) window.location.href = '/employee.html';
    else document.getElementById('errorMsg').innerText = data.error;
}
</script>
</body>
</html>'''

@app.route('/admin.html')
def admin_page():
    return '''
<!DOCTYPE html>
<html>
<head>
    <title>ADP Admin Portal</title>
    <style>
        *{margin:0;padding:0;box-sizing:border-box;}
        body{font-family: Arial, sans-serif; background: #f0f2f5; padding: 20px;}
        .container{max-width: 1200px; margin: 0 auto;}
        .header{background: #003057; color: white; padding: 20px; border-radius: 12px; margin-bottom: 20px;}
        .card{background: white; border-radius: 12px; padding: 20px; margin-bottom: 20px; box-shadow: 0 2px 10px rgba(0,0,0,0.1);}
        .card h3{margin-bottom: 15px; color: #003057;}
        input, select{width: 100%; padding: 10px; margin: 8px 0; border: 1px solid #ddd; border-radius: 6px;}
        button{background: #003057; color: white; border: none; padding: 10px 20px; border-radius: 6px; cursor: pointer; margin: 5px;}
        .success{background: #d4edda; color: #155724; padding: 10px; border-radius: 8px; margin: 10px 0;}
        .error{background: #f8d7da; color: #721c24; padding: 10px; border-radius: 8px; margin: 10px 0;}
        .row{display: flex; gap: 20px; flex-wrap: wrap;}
        .col{flex: 1; min-width: 200px;}
        table{width: 100%; border-collapse: collapse;}
        th,td{padding: 12px; text-align: left; border-bottom: 1px solid #eee;}
        th{background: #f8f9fa; color: #003057;}
        .tab{display: inline-block; padding: 10px 20px; background: #e9ecef; cursor: pointer; border-radius: 8px 8px 0 0; margin-right: 5px;}
        .tab.active{background: #003057; color: white;}
        .tab-content{display: none; padding: 20px; background: white; border-radius: 0 12px 12px 12px; margin-top: -1px;}
        .tab-content.active{display: block;}
    </style>
</head>
<body>
<div class="container">
    <div class="header"><h1>ADP Admin Portal</h1><p>Payroll Management System</p></div>
    
    <div id="loginSection">
        <div class="card" style="max-width: 400px; margin: 0 auto;">
            <h3>Admin Login</h3>
            <input type="text" id="adminUsername" placeholder="Username" value="admin">
            <input type="password" id="adminPassword" placeholder="Password" value="Admin123!">
            <button onclick="adminLogin()">Login</button>
            <div id="adminError"></div>
        </div>
    </div>
    
    <div id="dashboardSection" style="display:none;">
        <div><span class="tab active" onclick="showTab('employees')">Employees</span><span class="tab" onclick="showTab('payroll')">Run Payroll</span><span class="tab" onclick="showTab('stubs')">Pay Stubs</span></div>
        
        <div id="employees" class="tab-content active">
            <div class="card"><h3>Add Employee</h3>
                <div class="row"><div class="col"><label>Full Name</label><input type="text" id="empName"></div><div class="col"><label>Email</label><input type="email" id="empEmail"></div></div>
                <div class="row"><div class="col"><label>Phone</label><input type="text" id="empPhone"></div><div class="col"><label>SSN (Last 4)</label><input type="text" id="empSsn" maxlength="4"></div></div>
                <div class="row"><div class="col"><label>Address</label><input type="text" id="empAddress"></div><div class="col"><label>City</label><input type="text" id="empCity"></div></div>
                <div class="row"><div class="col"><label>State</label><input type="text" id="empState" value="FL"></div><div class="col"><label>ZIP</label><input type="text" id="empZip"></div></div>
                <div class="row"><div class="col"><label>Pay Rate ($/hr)</label><input type="number" id="empRate" step="0.01"></div><div class="col"><label>Filing Status</label><select id="empFiling"><option value="single">Single</option><option value="married">Married</option></select></div></div>
                <div class="row"><div class="col"><label>Direct Deposit Bank</label><input type="text" id="empBank"></div><div class="col"><label>Account Number</label><input type="text" id="empAccount"></div></div>
                <div class="row"><div class="col"><label>Password</label><input type="text" id="empPassword" value="Welcome123!"></div><div class="col"><label>Hire Date</label><input type="text" id="empHireDate" value=""></div></div>
                <button onclick="addEmployee()">Add Employee</button><div id="addResult"></div>
            </div>
            <div class="card"><h3>Employee Directory</h3><div id="employeesList"></div></div>
        </div>
        
        <div id="payroll" class="tab-content">
            <div class="card"><h3>Run Payroll</h3>
                <div class="row"><div class="col"><label>Select Employee</label><select id="payrollEmployee"></select></div><div class="col"><label>Hours Worked</label><input type="number" id="hoursWorked" value="80"></div></div>
                <div class="row"><div class="col"><label>Overtime Hours</label><input type="number" id="overtimeHours" value="0"></div></div>
                <button onclick="runPayroll()">Run Payroll</button><div id="payrollResult"></div>
            </div>
            <div class="card"><h3>Payroll History</h3><div id="payrollHistory"></div></div>
        </div>
        
        <div id="stubs" class="tab-content">
            <div class="card"><h3>Pay Stubs</h3><div id="stubsList"></div></div>
        </div>
    </div>
</div>
<script>
const today = new Date();
document.getElementById('empHireDate').value = `${today.getMonth()+1}/${today.getDate()}/${today.getFullYear()}`;

async function adminLogin(){
    const username = document.getElementById('adminUsername').value;
    const password = document.getElementById('adminPassword').value;
    const res = await fetch('/api/auth/admin/login', {
        method: 'POST', headers: {'Content-Type': 'application/json'}, credentials: 'include',
        body: JSON.stringify({username: username, password: password})
    });
    const data = await res.json();
    if(data.success){
        document.getElementById('loginSection').style.display = 'none';
        document.getElementById('dashboardSection').style.display = 'block';
        loadEmployees(); loadPayrollHistory(); loadStubs();
    } else { document.getElementById('adminError').innerText = data.error; }
}

async function loadEmployees(){
    const res = await fetch('/api/admin/employees', {credentials: 'include'});
    const data = await res.json();
    if(data.employees){
        document.getElementById('employeesList').innerHTML = `<table style="width:100%"><tr><th>User ID</th><th>Name</th><th>Email</th><th>Rate</th><th>Status</th><th>Action</th></tr>${data.employees.map(e => `<tr><td>${e.user_id}</td><td>${e.full_name}</td><td>${e.email || '-'}</td><td>$${e.pay_rate}/hr</td><td>${e.is_active ? 'Active' : 'Inactive'}</td><td><button onclick="selectForPayroll(${e.id})">Pay</button></td></tr>`).join('')}</table>`;
        const select = document.getElementById('payrollEmployee');
        select.innerHTML = '<option value="">Select Employee</option>' + data.employees.map(e => `<option value="${e.id}">${e.full_name} ($${e.pay_rate}/hr)</option>`).join('');
    }
}

async function addEmployee(){
    const data = {
        full_name: document.getElementById('empName').value, email: document.getElementById('empEmail').value,
        phone: document.getElementById('empPhone').value, ssn_last4: document.getElementById('empSsn').value,
        address: document.getElementById('empAddress').value, city: document.getElementById('empCity').value,
        state: document.getElementById('empState').value, zip_code: document.getElementById('empZip').value,
        pay_rate: parseFloat(document.getElementById('empRate').value), filing_status: document.getElementById('empFiling').value,
        direct_deposit_bank: document.getElementById('empBank').value, direct_deposit_account: document.getElementById('empAccount').value,
        password: document.getElementById('empPassword').value, hire_date: document.getElementById('empHireDate').value
    };
    if(!data.full_name || !data.pay_rate){ alert('Name and pay rate required'); return; }
    const res = await fetch('/api/admin/employees', {
        method: 'POST', headers: {'Content-Type': 'application/json'}, credentials: 'include',
        body: JSON.stringify(data)
    });
    const result = await res.json();
    if(result.success){
        document.getElementById('addResult').innerHTML = `<div class="success">✅ Employee added! User ID: ${result.user_id}, Password: ${result.default_password}</div>`;
        loadEmployees();
    } else { document.getElementById('addResult').innerHTML = `<div class="error">❌ ${result.error}</div>`; }
}

async function runPayroll(){
    const employeeId = document.getElementById('payrollEmployee').value;
    const hours = parseFloat(document.getElementById('hoursWorked').value);
    const overtime = parseFloat(document.getElementById('overtimeHours').value);
    if(!employeeId){ alert('Select employee'); return; }
    const res = await fetch('/api/admin/payroll/generate', {
        method: 'POST', headers: {'Content-Type': 'application/json'}, credentials: 'include',
        body: JSON.stringify({employee_id: parseInt(employeeId), hours: hours, overtime: overtime})
    });
    const data = await res.json();
    if(data.success){
        document.getElementById('payrollResult').innerHTML = `<div class="success">✅ Payroll generated! Gross: $${data.gross_pay}, Net: $${data.net_pay}</div>`;
        loadPayrollHistory(); loadStubs();
    } else { document.getElementById('payrollResult').innerHTML = `<div class="error">❌ ${data.error}</div>`; }
}

async function loadPayrollHistory(){
    const res = await fetch('/api/payroll/stubs', {credentials: 'include'});
    const data = await res.json();
    if(data.stubs && data.stubs.length > 0){
        document.getElementById('payrollHistory').innerHTML = `<table style="width:100%"><tr><th>Date</th><th>Employee</th><th>Gross</th><th>Net</th><th>Downloads</th></tr>${data.stubs.map(s => `<tr><td>${s.pay_date}</td><td>${s.employee_name}</td><td>$${s.gross_pay}</td><td>$${s.net_pay}</td><td>${s.download_count}</td></tr>`).join('')}</table>`;
    } else { document.getElementById('payrollHistory').innerHTML = '<p>No payroll runs yet</p>'; }
}

async function loadStubs(){
    const res = await fetch('/api/payroll/stubs', {credentials: 'include'});
    const data = await res.json();
    if(data.stubs && data.stubs.length > 0){
        document.getElementById('stubsList').innerHTML = `<table style="width:100%"><tr><th>Stub #</th><th>Employee</th><th>Pay Date</th><th>Net Pay</th><th>Action</th></tr>${data.stubs.map(s => `<tr><td>${s.stub_number}</td><td>${s.employee_name}</td><td>${s.pay_date}</td><td>$${s.net_pay}</td><td><button onclick="downloadStub(${s.id})">Download PDF</button></td></tr>`).join('')}</table>`;
    } else { document.getElementById('stubsList').innerHTML = '<p>No pay stubs generated yet</p>'; }
}

function downloadStub(stubId){ window.open(`/api/payroll/stub/${stubId}/download`, '_blank'); }
function selectForPayroll(id){ document.getElementById('payrollEmployee').value = id; showTab('payroll'); }
function showTab(tabName){
    document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
    document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
    event.target.classList.add('active');
    document.getElementById(tabName).classList.add('active');
    if(tabName === 'employees') loadEmployees();
    if(tabName === 'stubs') loadStubs();
}
</script>
</body>
</html>'''

@app.route('/employee.html')
def employee_dashboard():
    return '''
<!DOCTYPE html>
<html>
<head>
    <title>ADP Employee Portal</title>
    <style>
        *{margin:0;padding:0;box-sizing:border-box;}
        body{font-family: Arial, sans-serif; background: #f0f2f5; padding: 20px;}
        .container{max-width: 1000px; margin: 0 auto;}
        .header{background: #003057; color: white; padding: 20px; border-radius: 12px; margin-bottom: 20px;}
        .card{background: white; border-radius: 12px; padding: 20px; margin-bottom: 20px;}
        button{background: #003057; color: white; border: none; padding: 10px 20px; border-radius: 6px; cursor: pointer;}
        .logout{float: right; background: #dc3545;}
        table{width: 100%; border-collapse: collapse;}
        th,td{padding: 12px; text-align: left; border-bottom: 1px solid #eee;}
        th{background: #f8f9fa;}
    </style>
</head>
<body>
<div class="container">
    <div class="header"><h1>ADP Employee Portal</h1><p>Welcome, <span id="employeeName"></span> | <span id="employeeId"></span><button class="logout" onclick="logout()">Logout</button></p></div>
    <div class="card"><h3>My Pay Stubs</h3><div id="stubsList"></div></div>
</div>
<script>
async function loadEmployeeInfo(){
    const res = await fetch('/api/auth/me', {credentials: 'include'});
    const data = await res.json();
    if(data.user && data.user.type === 'employee'){
        document.getElementById('employeeName').innerText = data.user.full_name;
        document.getElementById('employeeId').innerText = data.user.user_id;
        loadMyStubs();
    } else { window.location.href = '/login.html'; }
}

async function loadMyStubs(){
    const res = await fetch('/api/payroll/stubs', {credentials: 'include'});
    const data = await res.json();
    if(data.stubs && data.stubs.length > 0){
        document.getElementById('stubsList').innerHTML = `<table style="width:100%"><tr><th>Stub #</th><th>Pay Date</th><th>Gross Pay</th><th>Net Pay</th><th>Action</th></tr>${data.stubs.map(s => `<tr><td>${s.stub_number}</td><td>${s.pay_date}</td><td>$${s.gross_pay}</td><td>$${s.net_pay}</td><td><button onclick="downloadStub(${s.id})">Download PDF</button></td></tr>`).join('')}</table>`;
    } else { document.getElementById('stubsList').innerHTML = '<p>No pay stubs available</p>'; }
}

function downloadStub(stubId){ window.open(`/api/payroll/stub/${stubId}/download`, '_blank'); }
async function logout(){
    await fetch('/api/auth/logout', {method: 'POST', credentials: 'include'});
    window.location.href = '/login.html';
}
loadEmployeeInfo();
</script>
</body>
</html>'''

application = app

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
