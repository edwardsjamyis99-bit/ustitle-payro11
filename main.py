import os
import json
import secrets
import bcrypt
import re
from datetime import datetime, timedelta
from flask import Flask, request, jsonify, session, make_response
from flask_sqlalchemy import SQLAlchemy
from flask_cors import CORS
from dotenv import load_dotenv
from functools import wraps
import random
import csv
from io import StringIO

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
    user_id = db.Column(db.String(50), unique=True)  # ADP-style user ID for login
    password_hash = db.Column(db.String(128))  # Employee login password
    full_name = db.Column(db.String(200), nullable=False)
    preferred_name = db.Column(db.String(100))
    address = db.Column(db.Text)
    city = db.Column(db.String(100))
    state = db.Column(db.String(50))
    zip_code = db.Column(db.String(20))
    ssn_last4 = db.Column(db.String(4))
    phone = db.Column(db.String(20))
    email = db.Column(db.String(120))
    hire_date = db.Column(db.String(20))
    termination_date = db.Column(db.String(20))
    pay_rate = db.Column(db.Float)
    pay_type = db.Column(db.String(20))  # hourly, salary
    pay_frequency = db.Column(db.String(20), default='bi-weekly')
    filing_status = db.Column(db.String(20), default='single')
    federal_allowances = db.Column(db.Integer, default=2)
    direct_deposit_bank = db.Column(db.String(100))
    direct_deposit_account = db.Column(db.String(50))
    direct_deposit_routing = db.Column(db.String(50))
    is_active = db.Column(db.Boolean, default=True)
    is_pto_accrual = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class PayrollRun(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    employee_id = db.Column(db.Integer, db.ForeignKey('employee.id'))
    payroll_sequence = db.Column(db.Integer)
    pay_period_start = db.Column(db.String(20))
    pay_period_end = db.Column(db.String(20))
    pay_date = db.Column(db.String(20))
    check_number = db.Column(db.String(20))
    
    # Earnings
    hours_worked = db.Column(db.Float, default=80.0)
    overtime_hours = db.Column(db.Float, default=0)
    regular_pay = db.Column(db.Float)
    overtime_pay = db.Column(db.Float)
    gross_pay = db.Column(db.Float)
    
    # Deductions
    federal_tax = db.Column(db.Float)
    social_security = db.Column(db.Float)
    medicare = db.Column(db.Float)
    state_tax = db.Column(db.Float, default=0.0)
    local_tax = db.Column(db.Float, default=0.0)
    total_deductions = db.Column(db.Float)
    
    # Net Pay
    net_pay = db.Column(db.Float)
    
    # YTD totals
    ytd_gross = db.Column(db.Float)
    ytd_federal_tax = db.Column(db.Float)
    ytd_social_security = db.Column(db.Float)
    ytd_medicare = db.Column(db.Float)
    
    status = db.Column(db.String(20), default='processed')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class PayStub(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    payroll_id = db.Column(db.Integer, db.ForeignKey('payroll_run.id'))
    employee_id = db.Column(db.Integer, db.ForeignKey('employee.id'))
    stub_number = db.Column(db.String(50), unique=True)
    pdf_data = db.Column(db.Text)
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
    logo_url = db.Column(db.String(500))
    updated_at = db.Column(db.DateTime, default=datetime.utcnow)

with app.app_context():
    db.create_all()
    
    # Create default admin if none exists
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
    
    # Create default company info if none exists
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
    return f"STUB-{datetime.now().strftime('%Y%m%d')}-{random.randint(1000, 9999)}"

def generate_check_number():
    return f"{datetime.now().strftime('%y%m%d')}{random.randint(1000, 9999)}"

def calculate_federal_tax(gross_pay, filing_status):
    """2026 Federal Income Tax calculation (bi-weekly)"""
    if filing_status == 'single':
        if gross_pay <= 459:
            tax = 0
        elif gross_pay <= 1610:
            tax = (gross_pay - 459) * 0.10
        elif gross_pay <= 3830:
            tax = 115.10 + (gross_pay - 1610) * 0.12
        elif gross_pay <= 8970:
            tax = 381.50 + (gross_pay - 3830) * 0.22
        else:
            tax = 1504.30 + (gross_pay - 8970) * 0.24
    else:
        if gross_pay <= 1072:
            tax = 0
        elif gross_pay <= 3212:
            tax = (gross_pay - 1072) * 0.10
        elif gross_pay <= 7662:
            tax = 214.00 + (gross_pay - 3212) * 0.12
        elif gross_pay <= 17940:
            tax = 748.00 + (gross_pay - 7662) * 0.22
        else:
            tax = 3009.16 + (gross_pay - 17940) * 0.24
    return round(tax, 2)

def calculate_social_security(gross_pay, ytd_gross=0):
    wage_base = 184500
    if ytd_gross + gross_pay > wage_base:
        taxable = max(0, wage_base - ytd_gross)
        return round(taxable * 0.062, 2)
    return round(gross_pay * 0.062, 2)

def calculate_medicare(gross_pay):
    return round(gross_pay * 0.0145, 2)

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
        session['user_type'] = 'admin'
        return jsonify({'success': True, 'user': {'username': admin.username, 'full_name': admin.full_name, 'role': admin.role}})
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
        session['user_type'] = 'employee'
        return jsonify({'success': True, 'user': {'user_id': employee.user_id, 'full_name': employee.full_name}})
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
        'pay_rate': e.pay_rate, 'pay_type': e.pay_type,
        'filing_status': e.filing_status, 'is_active': e.is_active,
        'hire_date': e.hire_date, 'direct_deposit_bank': e.direct_deposit_bank
    } for e in employees]})

@app.route('/api/admin/employees', methods=['POST'])
@admin_required
def add_employee():
    try:
        data = request.json
        employee_id = generate_employee_id()
        user_id = generate_user_id(data['full_name'])
        
        # Set default password (user must change on first login)
        default_password = bcrypt.hashpw(data.get('password', 'Welcome123!').encode(), bcrypt.gensalt())
        
        employee = Employee(
            employee_id=employee_id,
            user_id=user_id,
            password_hash=default_password,
            full_name=data['full_name'],
            preferred_name=data.get('preferred_name', ''),
            address=data.get('address', ''),
            city=data.get('city', ''),
            state=data.get('state', ''),
            zip_code=data.get('zip_code', ''),
            ssn_last4=data.get('ssn_last4', ''),
            phone=data.get('phone', ''),
            email=data.get('email', ''),
            hire_date=data.get('hire_date', datetime.now().strftime('%m/%d/%Y')),
            pay_rate=data['pay_rate'],
            pay_type=data.get('pay_type', 'hourly'),
            filing_status=data.get('filing_status', 'single'),
            direct_deposit_bank=data.get('direct_deposit_bank', ''),
            direct_deposit_account=data.get('direct_deposit_account', ''),
            direct_deposit_routing=data.get('direct_deposit_routing', '')
        )
        db.session.add(employee)
        db.session.commit()
        
        return jsonify({
            'success': True,
            'employee_id': employee_id,
            'user_id': user_id,
            'default_password': data.get('password', 'Welcome123!')
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 400

@app.route('/api/admin/employees/<int:emp_id>', methods=['PUT'])
@admin_required
def update_employee(emp_id):
    try:
        employee = Employee.query.get(emp_id)
        if not employee:
            return jsonify({'error': 'Employee not found'}), 404
        data = request.json
        employee.full_name = data.get('full_name', employee.full_name)
        employee.email = data.get('email', employee.email)
        employee.phone = data.get('phone', employee.phone)
        employee.pay_rate = data.get('pay_rate', employee.pay_rate)
        employee.pay_type = data.get('pay_type', employee.pay_type)
        employee.filing_status = data.get('filing_status', employee.filing_status)
        employee.is_active = data.get('is_active', employee.is_active)
        employee.direct_deposit_bank = data.get('direct_deposit_bank', employee.direct_deposit_bank)
        db.session.commit()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 400

@app.route('/api/admin/employees/<int:emp_id>/reset_password', methods=['POST'])
@admin_required
def reset_employee_password(emp_id):
    try:
        employee = Employee.query.get(emp_id)
        if not employee:
            return jsonify({'error': 'Employee not found'}), 404
        new_password = secrets.token_hex(4)
        employee.password_hash = bcrypt.hashpw(new_password.encode(), bcrypt.gensalt())
        db.session.commit()
        return jsonify({'success': True, 'new_password': new_password})
    except Exception as e:
        return jsonify({'error': str(e)}), 400

# ============= PAYROLL ENDPOINTS =============
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
        payroll_sequence = len(previous_runs) + 1
        ytd_gross = sum(r.gross_pay for r in previous_runs) + gross_pay
        
        federal_tax = calculate_federal_tax(gross_pay, employee.filing_status)
        social_security = calculate_social_security(gross_pay, ytd_gross - gross_pay)
        medicare = calculate_medicare(gross_pay)
        state_tax = 0.0
        
        total_deductions = federal_tax + social_security + medicare + state_tax
        net_pay = gross_pay - total_deductions
        check_number = generate_check_number()
        
        payroll = PayrollRun(
            employee_id=employee.id,
            payroll_sequence=payroll_sequence,
            pay_period_start=pay_period_start.strftime('%m/%d/%Y'),
            pay_period_end=pay_period_end.strftime('%m/%d/%Y'),
            pay_date=datetime.now().strftime('%m/%d/%Y'),
            check_number=check_number,
            hours_worked=hours,
            overtime_hours=overtime,
            regular_pay=regular_pay,
            overtime_pay=overtime_pay,
            gross_pay=gross_pay,
            federal_tax=federal_tax,
            social_security=social_security,
            medicare=medicare,
            state_tax=state_tax,
            total_deductions=total_deductions,
            net_pay=net_pay,
            ytd_gross=ytd_gross,
            ytd_federal_tax=sum(r.federal_tax for r in previous_runs) + federal_tax,
            ytd_social_security=sum(r.social_security for r in previous_runs) + social_security,
            ytd_medicare=sum(r.medicare for r in previous_runs) + medicare
        )
        db.session.add(payroll)
        db.session.commit()
        
        # Generate pay stub
        stub_number = generate_stub_number()
        pay_stub = PayStub(
            payroll_id=payroll.id,
            employee_id=employee.id,
            stub_number=stub_number
        )
        db.session.add(pay_stub)
        db.session.commit()
        
        return jsonify({
            'success': True,
            'payroll_id': payroll.id,
            'stub_number': stub_number,
            'gross_pay': gross_pay,
            'net_pay': net_pay,
            'check_number': check_number,
            'ytd_gross': ytd_gross
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 400

@app.route('/api/payroll/stubs', methods=['GET'])
@login_required
def get_my_stubs():
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
                'id': stub.id,
                'stub_number': stub.stub_number,
                'employee_name': employee.full_name,
                'pay_date': payroll.pay_date,
                'gross_pay': payroll.gross_pay,
                'net_pay': payroll.net_pay,
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
        
        # Update download count
        stub.download_count += 1
        db.session.commit()
        
        payroll = PayrollRun.query.get(stub.payroll_id)
        employee = Employee.query.get(stub.employee_id)
        company = CompanyInfo.query.first()
        
        micr_line = f"⑆{company.routing_number}⑆{company.account_number[-4:]}⑆{payroll.check_number}⑆"
        
        html = f'''<!DOCTYPE html>
<html>
<head>
    <title>ADP Pay Stub - {employee.full_name}</title>
    <meta charset="UTF-8">
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            font-family: 'Helvetica Neue', Arial, sans-serif;
            background: #e8e8e8;
            display: flex;
            justify-content: center;
            padding: 40px;
        }}
        .adp-stub {{
            width: 8.5in;
            background: white;
            box-shadow: 0 0 15px rgba(0,0,0,0.15);
        }}
        .header {{
            background: #003057;
            color: white;
            padding: 20px;
            text-align: center;
        }}
        .adp-logo {{
            font-size: 28px;
            font-weight: bold;
            letter-spacing: 2px;
        }}
        .adp-tagline {{
            font-size: 10px;
            opacity: 0.8;
            margin-top: 5px;
        }}
        .company-info {{
            padding: 15px;
            background: #f5f5f5;
            border-bottom: 1px solid #ddd;
            text-align: center;
        }}
        .company-name {{
            font-size: 18px;
            font-weight: bold;
            color: #003057;
        }}
        .section {{
            padding: 15px;
            border-bottom: 1px solid #eee;
        }}
        .section-title {{
            background: #e8e8e8;
            padding: 8px 12px;
            font-weight: bold;
            font-size: 12px;
            color: #003057;
            margin-bottom: 10px;
        }}
        .row {{
            display: flex;
            justify-content: space-between;
            margin: 8px 0;
            font-size: 11px;
        }}
        table {{
            width: 100%;
            border-collapse: collapse;
            margin: 10px 0;
            font-size: 10px;
        }}
        th, td {{
            border: 1px solid #ddd;
            padding: 8px;
            text-align: left;
        }}
        th {{
            background: #f0f0f0;
            font-weight: bold;
        }}
        .total-row {{
            font-weight: bold;
            background: #f9f9f9;
        }}
        .net-pay-box {{
            background: #003057;
            color: white;
            padding: 12px;
            text-align: center;
            margin: 15px 0;
        }}
        .net-pay-amount {{
            font-size: 24px;
            font-weight: bold;
        }}
        .micr {{
            font-family: 'Courier New', monospace;
            font-size: 11px;
            letter-spacing: 1px;
            background: #f8f8f8;
            padding: 10px;
            text-align: center;
            border-top: 1px solid #ddd;
        }}
        .footer {{
            font-size: 8px;
            text-align: center;
            padding: 10px;
            color: #666;
            background: #f5f5f5;
        }}
        @media print {{
            body {{ background: white; padding: 0; }}
            .adp-stub {{ box-shadow: none; }}
        }}
    </style>
</head>
<body>
<div class="adp-stub">
    <div class="header">
        <div class="adp-logo">ADP</div>
        <div class="adp-tagline">Automatic Data Processing | Payroll Services</div>
    </div>
    
    <div class="company-info">
        <div class="company-name">{company.company_name}</div>
        <div>{company.company_address}</div>
        <div>Phone: {company.company_phone} | EIN: {company.company_ein}</div>
    </div>
    
    <div class="section">
        <div class="section-title">EMPLOYEE INFORMATION</div>
        <div class="row"><span><strong>Name:</strong> {employee.full_name}</span><span><strong>Employee ID:</strong> {employee.employee_id}</span></div>
        <div class="row"><span><strong>User ID:</strong> {employee.user_id}</span><span><strong>SSN:</strong> XXX-XX-{employee.ssn_last4}</span></div>
        <div class="row"><span><strong>Pay Period:</strong> {payroll.pay_period_start} - {payroll.pay_period_end}</span><span><strong>Pay Date:</strong> {payroll.pay_date}</span></div>
        <div class="row"><span><strong>Check Number:</strong> {payroll.check_number}</span><span><strong>Pay Frequency:</strong> Bi-Weekly</span></div>
    </div>
    
    <div class="section">
        <div class="section-title">EARNINGS</div>
        <table>
            <thead><tr><th>Description</th><th>Hours</th><th>Rate</th><th>Current</th><th>YTD</th></tr></thead>
            <tbody>
                <tr><td>Regular Pay</td><td>{payroll.hours_worked}</td><td>${employee.pay_rate:.2f}</td><td>${payroll.regular_pay:.2f}</td><td>-</td></tr>
                {f'<tr><td>Overtime</td><td>{payroll.overtime_hours}</td><td>${employee.pay_rate * 1.5:.2f}</td><td>${payroll.overtime_pay:.2f}</td><td>-</td></tr>' if payroll.overtime_hours > 0 else ''}
                <tr class="total-row"><td colspan="3"><strong>GROSS PAY</strong></td><td><strong>${payroll.gross_pay:.2f}</strong></td><td><strong>${payroll.ytd_gross:.2f}</strong></td></tr>
            </tbody>
        </table>
    </div>
    
    <div class="section">
        <div class="section-title">DEDUCTIONS</div>
        <table>
            <thead><tr><th>Description</th><th>Rate</th><th>Current</th><th>YTD</th></tr></thead>
            <tbody>
                <tr><td>Federal Income Tax</td><td>{calculate_federal_tax(payroll.gross_pay, employee.filing_status) / payroll.gross_pay * 100:.1f}%</td><td>${payroll.federal_tax:.2f}</td><td>${payroll.ytd_federal_tax:.2f}</td></tr>
                <tr><td>Social Security</td><td>6.2%</td><td>${payroll.social_security:.2f}</td><td>${payroll.ytd_social_security:.2f}</td></tr>
                <tr><td>Medicare</td><td>1.45%</td><td>${payroll.medicare:.2f}</td><td>${payroll.ytd_medicare:.2f}</td></tr>
                <tr><td>Florida State Tax</td><td>0.0%</td><td>$0.00</td><td>$0.00</td></tr>
                <tr class="total-row"><td colspan="2"><strong>TOTAL DEDUCTIONS</strong></td><td><strong>${payroll.total_deductions:.2f}</strong></td><td><strong>${payroll.ytd_federal_tax + payroll.ytd_social_security + payroll.ytd_medicare:.2f}</strong></td></tr>
            </tbody>
        </table>
    </div>
    
    <div class="net-pay-box">
        <div>NET PAY</div>
        <div class="net-pay-amount">${payroll.net_pay:.2f}</div>
        <div style="font-size: 10px; margin-top: 5px;">Direct Deposit: {employee.direct_deposit_bank or 'Check'} ****{employee.direct_deposit_account[-4:] if employee.direct_deposit_account else 'N/A'}</div>
    </div>
    
    <div class="micr">
        {micr_line}
    </div>
    
    <div class="footer">
        <p>This is an official ADP Pay Statement. For verification, contact payroll@ustitleescrow.com</p>
        <p>Stub ID: {stub.stub_number} | Generated: {datetime.now().strftime('%m/%d/%Y %H:%M:%S')}</p>
        <p>This document is electronically generated and approved by U.S. TITLE & ESCROW INC</p>
    </div>
</div>
<script>window.onload=function(){{setTimeout(function(){{window.print();}},500);}}</script>
</body>
</html>'''
        return make_response(html)
    except Exception as e:
        return jsonify({'error': str(e)}), 400

# ============= COMPANY INFO ENDPOINTS =============
@app.route('/api/company/info', methods=['GET'])
def get_company_info():
    company = CompanyInfo.query.first()
    return jsonify({
        'company_name': company.company_name,
        'company_address': company.company_address,
        'company_phone': company.company_phone,
        'company_email': company.company_email,
        'bank_name': company.bank_name,
        'routing_number': company.routing_number
    })

@app.route('/api/admin/company', methods=['PUT'])
@admin_required
def update_company():
    try:
        company = CompanyInfo.query.first()
        data = request.json
        company.company_name = data.get('company_name', company.company_name)
        company.company_address = data.get('company_address', company.company_address)
        company.company_phone = data.get('company_phone', company.company_phone)
        company.company_email = data.get('company_email', company.company_email)
        company.bank_name = data.get('bank_name', company.bank_name)
        company.routing_number = data.get('routing_number', company.routing_number)
        db.session.commit()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 400

# ============= FRONTEND =============
@app.route('/')
def home():
    return '<h1>ADP Style Payroll System</h1><p><a href="/login.html">Login</a> | <a href="/admin.html">Admin Login</a></p>'

@app.route('/login.html')
def login_page():
    return '''
<!DOCTYPE html>
<html>
<head>
    <title>ADP Payroll - Employee Login</title>
    <style>
        *{margin:0;padding:0;box-sizing:border-box;}
        body{font-family:'Segoe UI',Arial,sans-serif;background:#003057;min-height:100vh;display:flex;justify-content:center;align-items:center;}
        .login-container{background:white;padding:40px;border-radius:12px;width:400px;box-shadow:0 10px 30px rgba(0,0,0,0.2);}
        .logo{text-align:center;margin-bottom:30px;}
        .logo h1{color:#003057;font-size:28px;}
        .logo p{color:#666;font-size:12px;}
        input{width:100%;padding:12px;margin:10px 0;border:1px solid #ddd;border-radius:6px;}
        button{width:100%;padding:12px;background:#003057;color:white;border:none;border-radius:6px;cursor:pointer;font-size:16px;}
        button:hover{background:#002244;}
        .error{color:red;margin-top:10px;text-align:center;}
        .switch{text-align:center;margin-top:20px;}
        .switch a{color:#003057;text-decoration:none;}
    </style>
</head>
<body>
<div class="login-container">
    <div class="logo">
        <h1>ADP</h1>
        <p>Payroll Services</p>
    </div>
    <h3 style="margin-bottom:20px;">Employee Login</h3>
    <input type="text" id="userId" placeholder="User ID (e.g., john.doe123)">
    <input type="password" id="password" placeholder="Password">
    <button onclick="login()">Sign In</button>
    <div id="errorMsg" class="error"></div>
    <div class="switch"><a href="/admin.html">Admin Login</a></div>
</div>
<script>
async function login(){
    const userId=document.getElementById('userId').value;
    const password=document.getElementById('password').value;
    const res=await fetch('/api/auth/employee/login',{
        method:'POST',
        headers:{'Content-Type':'application/json'},
        credentials:'include',
        body:JSON.stringify({user_id:userId,password:password})
    });
    const data=await res.json();
    if(data.success){
        window.location.href='/employee.html';
    }else{
        document.getElementById('errorMsg').innerText=data.error;
    }
}
</script>
</body>
</html>
    '''

@app.route('/admin.html')
def admin_page():
    return '''
<!DOCTYPE html>
<html>
<head>
    <title>ADP Admin Portal</title>
    <style>
        *{margin:0;padding:0;box-sizing:border-box;}
        body{font-family:'Segoe UI',Arial,sans-serif;background:#f0f2f5;padding:20px;}
        .container{max-width:1400px;margin:0 auto;}
        .header{background:#003057;color:white;padding:20px;border-radius:12px;margin-bottom:20px;}
        .card{background:white;border-radius:12px;padding:20px;margin-bottom:20px;box-shadow:0 2px 10px rgba(0,0,0,0.1);}
        .card h3{margin-bottom:15px;color:#003057;border-bottom:2px solid #e0e0e0;padding-bottom:10px;}
        input,select,textarea{width:100%;padding:10px;margin:8px 0;border:1px solid #ddd;border-radius:6px;}
        button{background:#003057;color:white;border:none;padding:10px 20px;border-radius:6px;cursor:pointer;margin:5px;}
        .success{background:#d4edda;color:#155724;padding:10px;border-radius:8px;margin:10px 0;}
        .error{background:#f8d7da;color:#721c24;padding:10px;border-radius:8px;margin:10px 0;}
        .row{display:flex;gap:20px;flex-wrap:wrap;}
        .col{flex:1;min-width:250px;}
        table{width:100%;border-collapse:collapse;}
        th,td{padding:12px;text-align:left;border-bottom:1px solid #eee;}
        th{background:#f8f9fa;color:#003057;}
        .tab{display:inline-block;padding:10px 20px;background:#e9ecef;cursor:pointer;border-radius:8px 8px 0 0;margin-right:5px;}
        .tab.active{background:#003057;color:white;}
        .tab-content{display:none;padding:20px;background:white;border-radius:0 12px 12px 12px;margin-top:-1px;}
        .tab-content.active{display:block;}
    </style>
</head>
<body>
<div class="container">
    <div class="header">
        <h1>ADP Admin Portal</h1>
        <p>Automatic Data Processing | Payroll Management</p>
    </div>
    
    <div id="loginSection">
        <div class="card" style="max-width:400px;margin:0 auto;">
            <h3>Admin Login</h3>
            <input type="text" id="adminUsername" placeholder="Username or Email" value="admin">
            <input type="password" id="adminPassword" placeholder="Password" value="Admin123!">
            <button onclick="adminLogin()">Login</button>
            <div id="adminError"></div>
        </div>
    </div>
    
    <div id="dashboardSection" style="display:none;">
        <div>
            <span class="tab active" onclick="showTab('employees')">Employees</span>
            <span class="tab" onclick="showTab('payroll')">Run Payroll</span>
            <span class="tab" onclick="showTab('stubs')">Pay Stubs</span>
            <span class="tab" onclick="showTab('settings')">Company Settings</span>
        </div>
        
        <div id="employees" class="tab-content active">
            <div class="card">
                <h3>Add Employee</h3>
                <div class="row">
                    <div class="col"><label>Full Name</label><input type="text" id="empName"></div>
                    <div class="col"><label>Email</label><input type="email" id="empEmail"></div>
                </div>
                <div class="row">
                    <div class="col"><label>Phone</label><input type="text" id="empPhone"></div>
                    <div class="col"><label>SSN (Last 4)</label><input type="text" id="empSsn" maxlength="4"></div>
                </div>
                <div class="row">
                    <div class="col"><label>Address</label><input type="text" id="empAddress"></div>
                    <div class="col"><label>City</label><input type="text" id="empCity"></div>
                </div>
                <div class="row">
                    <div class="col"><label>State</label><input type="text" id="empState" value="FL"></div>
                    <div class="col"><label>ZIP</label><input type="text" id="empZip"></div>
                </div>
                <div class="row">
                    <div class="col"><label>Pay Rate ($/hr)</label><input type="number" id="empRate" step="0.01"></div>
                    <div class="col"><label>Filing Status</label><select id="empFiling"><option value="single">Single</option><option value="married">Married</option></select></div>
                </div>
                <div class="row">
                    <div class="col"><label>Direct Deposit Bank</label><input type="text" id="empBank"></div>
                    <div class="col"><label>Account Number</label><input type="text" id="empAccount"></div>
                </div>
                <div class="row">
                    <div class="col"><label>Default Password</label><input type="text" id="empPassword" placeholder="Welcome123!"></div>
                    <div class="col"><label>Hire Date</label><input type="text" id="empHireDate" value=""></div>
                </div>
                <button onclick="addEmployee()">Add Employee</button>
                <div id="addResult"></div>
            </div>
            <div class="card">
                <h3>Employee Directory</h3>
                <div id="employeesList"></div>
            </div>
        </div>
        
        <div id="payroll" class="tab-content">
            <div class="card">
                <h3>Run Payroll</h3>
                <div class="row">
                    <div class="col"><label>Select Employee</label><select id="payrollEmployee"></select></div>
                    <div class="col"><label>Hours Worked</label><input type="number" id="hoursWorked" value="80"></div>
                </div>
                <div class="row">
                    <div class="col"><label>Overtime Hours</label><input type="number" id="overtimeHours" value="0"></div>
                    <div class="col"></div>
                </div>
                <button onclick="runPayroll()">Run Payroll</button>
                <div id="payrollResult"></div>
            </div>
            <div class="card">
                <h3>Payroll History</h3>
                <div id="payrollHistory"></div>
            </div>
        </div>
        
        <div id="stubs" class="tab-content">
            <div class="card">
                <h3>Pay Stubs</h3>
                <div id="stubsList"></div>
            </div>
        </div>
        
        <div id="settings" class="tab-content">
            <div class="card">
                <h3>Company Information</h3>
                <div class="row">
                    <div class="col"><label>Company Name</label><input type="text" id="companyName" value="U.S. TITLE & ESCROW INC"></div>
                    <div class="col"><label>Company Address</label><textarea id="companyAddress" rows="2">2715 E Oakland Park Blvd, Suite 300, Fort Lauderdale, FL 33306</textarea></div>
                </div>
                <div class="row">
                    <div class="col"><label>Company Phone</label><input type="text" id="companyPhone" value="(954) 555-0123"></div>
                    <div class="col"><label>Company Email</label><input type="email" id="companyEmail" value="payroll@ustitleescrow.com"></div>
                </div>
                <div class="row">
                    <div class="col"><label>Bank Name</label><input type="text" id="bankName" value="SOUTH STATE BANK"></div>
                    <div class="col"><label>Routing Number</label><input type="text" id="routingNumber" value="063114030"></div>
                </div>
                <button onclick="saveCompanySettings()">Save Settings</button>
                <div id="settingsResult"></div>
            </div>
        </div>
    </div>
</div>

<script>
const today=new Date();
document.getElementById('empHireDate').value = `${today.getMonth()+1}/${today.getDate()}/${today.getFullYear()}`;

async function adminLogin(){
    const username=document.getElementById('adminUsername').value;
    const password=document.getElementById('adminPassword').value;
    const res=await fetch('/api/auth/admin/login',{
        method:'POST',
        headers:{'Content-Type':'application/json'},
        credentials:'include',
        body:JSON.stringify({username:username,password:password})
    });
    const data=await res.json();
    if(data.success){
        document.getElementById('loginSection').style.display='none';
        document.getElementById('dashboardSection').style.display='block';
        loadEmployees();
        loadPayrollHistory();
        loadStubs();
        loadCompanySettings();
    }else{
        document.getElementById('adminError').innerText=data.error;
    }
}

async function loadEmployees(){
    const res=await fetch('/api/admin/employees',{credentials:'include'});
    const data=await res.json();
    if(data.employees){
        document.getElementById('employeesList').innerHTML=`
            <table style="width:100%">
                <tr><th>ID</th><th>User ID</th><th>Name</th><th>Email</th><th>Rate</th><th>Status</th><th>Actions</th></tr>
                ${data.employees.map(e=>`
                    <tr>
                        <td>${e.employee_id}</td>
                        <td>${e.user_id}</td>
                        <td>${e.full_name}</td>
                        <td>${e.email||'-'}</td>
                        <td>$${e.pay_rate}/hr</td>
                        <td>${e.is_active?'Active':'Inactive'}</td>
                        <td><button onclick="selectForPayroll(${e.id})">Pay</button></td>
                    </tr>
                `).join('')}
            </table>
        `;
        const select=document.getElementById('payrollEmployee');
        select.innerHTML='<option value="">Select Employee</option>'+data.employees.map(e=>`<option value="${e.id}">${e.full_name} ($${e.pay_rate}/hr)</option>`).join('');
    }
}

async function addEmployee(){
    const data={
        full_name:document.getElementById('empName').value,
        email:document.getElementById('empEmail').value,
        phone:document.getElementById('empPhone').value,
        ssn_last4:document.getElementById('empSsn').value,
        address:document.getElementById('empAddress').value,
        city:document.getElementById('empCity').value,
        state:document.getElementById('empState').value,
        zip_code:document.getElementById('empZip').value,
        pay_rate:parseFloat(document.getElementById('empRate').value),
        filing_status:document.getElementById('empFiling').value,
        direct_deposit_bank:document.getElementById('empBank').value,
        direct_deposit_account:document.getElementById('empAccount').value,
        password:document.getElementById('empPassword').value,
        hire_date:document.getElementById('empHireDate').value
    };
    if(!data.full_name||!data.pay_rate){alert('Name and pay rate required');return;}
    const res=await fetch('/api/admin/employees',{
        method:'POST',
        headers:{'Content-Type':'application/json'},
        credentials:'include',
        body:JSON.stringify(data)
    });
    const result=await res.json();
    if(result.success){
        document.getElementById('addResult').innerHTML=`<div class="success">✅ Employee added! User ID: ${result.user_id}, Password: ${result.default_password}</div>`;
        loadEmployees();
    }else{
        document.getElementById('addResult').innerHTML=`<div class="error">❌ ${result.error}</div>`;
    }
}

async function runPayroll(){
    const employeeId=document.getElementById('payrollEmployee').value;
    const hours=parseFloat(document.getElementById('hoursWorked').value);
    const overtime=parseFloat(document.getElementById('overtimeHours').value);
    if(!employeeId){alert('Select employee');return;}
    const res=await fetch('/api/admin/payroll/generate',{
        method:'POST',
        headers:{'Content-Type':'application/json'},
        credentials:'include',
        body:JSON.stringify({employee_id:parseInt(employeeId),hours:hours,overtime:overtime})
    });
    const data=await res.json();
    if(data.success){
        document.getElementById('payrollResult').innerHTML=`<div class="success">✅ Payroll generated! Gross: $${data.gross_pay}, Net: $${data.net_pay}<br>Stub #: ${data.stub_number}</div>`;
        loadPayrollHistory();
        loadStubs();
    }else{
        document.getElementById('payrollResult').innerHTML=`<div class="error">❌ ${data.error}</div>`;
    }
}

async function loadPayrollHistory(){
    const res=await fetch('/api/payroll/stubs',{credentials:'include'});
    const data=await res.json();
    if(data.stubs&&data.stubs.length>0){
        document.getElementById('payrollHistory').innerHTML=`
            <table style="width:100%"><tr><th>Date</th><th>Employee</th><th>Gross</th><th>Net</th><th>Downloads</th></tr>
            ${data.stubs.map(s=>`<tr><td>${s.pay_date}</td><td>${s.employee_name}</td><td>$${s.gross_pay}</td><td>$${s.net_pay}</td><td>${s.download_count}</td></tr>`).join('')}</table>
        `;
    }else{
        document.getElementById('payrollHistory').innerHTML='<p>No payroll runs yet</p>';
    }
}

async function loadStubs(){
    const res=await fetch('/api/payroll/stubs',{credentials:'include'});
    const data=await res.json();
    if(data.stubs&&data.stubs.length>0){
        document.getElementById('stubsList').innerHTML=`
            <table style="width:100%"><tr><th>Stub #</th><th>Employee</th><th>Pay Date</th><th>Net Pay</th><th>Actions</th></tr>
            ${data.stubs.map(s=>`<tr><td>${s.stub_number}</td><td>${s.employee_name}</td><td>${s.pay_date}</td><td>$${s.net_pay}</td><td><button onclick="downloadStub(${s.id})">Download PDF</button></td></tr>`).join('')}</table>
        `;
    }else{
        document.getElementById('stubsList').innerHTML='<p>No pay stubs generated yet</p>';
    }
}

async function downloadStub(stubId){
    window.open(`/api/payroll/stub/${stubId}/download`,'_blank');
}

function selectForPayroll(id){
    document.getElementById('payrollEmployee').value=id;
    showTab('payroll');
}

async function loadCompanySettings(){
    const res=await fetch('/api/company/info');
    const data=await res.json();
    document.getElementById('companyName').value=data.company_name;
    document.getElementById('companyAddress').value=data.company_address;
    document.getElementById('companyPhone').value=data.company_phone;
    document.getElementById('companyEmail').value=data.company_email;
    document.getElementById('bankName').value=data.bank_name;
    document.getElementById('routingNumber').value=data.routing_number;
}

async function saveCompanySettings(){
    const data={
        company_name:document.getElementById('companyName').value,
        company_address:document.getElementById('companyAddress').value,
        company_phone:document.getElementById('companyPhone').value,
        company_email:document.getElementById('companyEmail').value,
        bank_name:document.getElementById('bankName').value,
        routing_number:document.getElementById('routingNumber').value
    };
    const res=await fetch('/api/admin/company',{
        method:'PUT',
        headers:{'Content-Type':'application/json'},
        credentials:'include',
        body:JSON.stringify(data)
    });
    if(res.ok){
        document.getElementById('settingsResult').innerHTML='<div class="success">✅ Settings saved!</div>';
    }else{
        document.getElementById('settingsResult').innerHTML='<div class="error">❌ Error saving</div>';
    }
}

function showTab(tabName){
    document.querySelectorAll('.tab').forEach(t=>t.classList.remove('active'));
    document.querySelectorAll('.tab-content').forEach(c=>c.classList.remove('active'));
    event.target.classList.add('active');
    document.getElementById(tabName).classList.add('active');
    if(tabName==='employees')loadEmployees();
    if(tabName==='stubs')loadStubs();
    if(tabName==='payroll')loadPayrollHistory();
}
</script>
</body>
</html>
    '''

@app.route('/employee.html')
def employee_dashboard():
    return '''
<!DOCTYPE html>
<html>
<head>
    <title>ADP Employee Portal</title>
    <style>
        *{margin:0;padding:0;box-sizing:border-box;}
        body{font-family:'Segoe UI',Arial,sans-serif;background:#f0f2f5;padding:20px;}
        .container{max-width:1000px;margin:0 auto;}
        .header{background:#003057;color:white;padding:20px;border-radius:12px;margin-bottom:20px;}
        .card{background:white;border-radius:12px;padding:20px;margin-bottom:20px;box-shadow:0 2px 10px rgba(0,0,0,0.1);}
        button{background:#003057;color:white;border:none;padding:10px 20px;border-radius:6px;cursor:pointer;}
        table{width:100%;border-collapse:collapse;}
        th,td{padding:12px;text-align:left;border-bottom:1px solid #eee;}
        th{background:#f8f9fa;}
        .logout{float:right;background:#dc3545;}
    </style>
</head>
<body>
<div class="container">
    <div class="header">
        <h1>ADP Employee Portal</h1>
        <p>Welcome, <span id="employeeName"></span> | <span id="employeeId"></span></p>
        <button class="logout" onclick="logout()">Logout</button>
    </div>
    
    <div class="card">
        <h3>My Pay Stubs</h3>
        <div id="stubsList"></div>
    </div>
</div>
<script>
async function loadEmployeeInfo(){
    const res=await fetch('/api/auth/me',{credentials:'include'});
    const data=await res.json();
    if(data.user&&data.user.type==='employee'){
        document.getElementById('employeeName').innerText=data.user.full_name;
        document.getElementById('employeeId').innerText=data.user.user_id;
        loadMyStubs();
    }else{
        window.location.href='/login.html';
    }
}

async function loadMyStubs(){
    const res=await fetch('/api/payroll/stubs',{credentials:'include'});
    const data=await res.json();
    if(data.stubs&&data.stubs.length>0){
        document.getElementById('stubsList').innerHTML=`
            <table style="width:100%">
                <tr><th>Stub #</th><th>Pay Date</th><th>Gross Pay</th><th>Net Pay</th><th>Actions</th></tr>
                ${data.stubs.map(s=>`<tr><td>${s.stub_number}</td><td>${s.pay_date}</td><td>$${s.gross_pay}</td><td>$${s.net_pay}</td><td><button onclick="downloadStub(${s.id})">View/Download</button></td></tr>`).join('')}
            </table>
        `;
    }else{
        document.getElementById('stubsList').innerHTML='<p>No pay stubs available</p>';
    }
}

async function downloadStub(stubId){
    window.open(`/api/payroll/stub/${stubId}/download`,'_blank');
}

async function logout(){
    await fetch('/api/auth/logout',{method:'POST',credentials:'include'});
    window.location.href='/login.html';
}

loadEmployeeInfo();
</script>
</body>
</html>
    '''

application = app

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
