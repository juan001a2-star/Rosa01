#!/usr/bin/env python3
"""
Sistema de Gestión para Negocio de Productos y Servicios
- Almacén / Inventario con contabilidad de entradas y salidas
- Caja registradora (ventas de productos, servicios y gastos)
- Portal de clientes (catálogo, horarios, citas)
"""

from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, session
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, date, time, timedelta
from functools import wraps
import os

app = Flask(__name__)

# Configuración para local y Render
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'negocio-secreto-cambiar-en-produccion-2026')

# DATABASE_URL (PostgreSQL en Render) o SQLite en /tmp
database_url = os.environ.get('DATABASE_URL')
if database_url:
    # Forzar el driver psycopg2, que está instalado en requirements.txt.
    # Render puede entregar DATABASE_URL con cualquiera de estos prefijos.
    if database_url.startswith('postgres://'):
        database_url = database_url.replace('postgres://', 'postgresql+psycopg2://', 1)
    elif database_url.startswith('postgresql://'):
        database_url = database_url.replace('postgresql://', 'postgresql+psycopg2://', 1)
    app.config['SQLALCHEMY_DATABASE_URI'] = database_url
else:
    # SQLite en /tmp (escribible en Render; el disco es efímero)
    db_path = os.path.join('/tmp', 'negocio.db')
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + db_path

app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'
login_manager.login_message = 'Debes iniciar sesión para acceder a esta página.'
login_manager.login_message_category = 'warning'

# ==================== MODELOS ====================

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    name = db.Column(db.String(120), nullable=False)
    phone = db.Column(db.String(30))
    role = db.Column(db.String(20), default='client')  # admin o client
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

class Category(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), unique=True, nullable=False)
    description = db.Column(db.Text)
    products = db.relationship('Product', backref='category', lazy='dynamic')

class Product(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    description = db.Column(db.Text)
    purchase_price = db.Column(db.Float, nullable=False, default=0.0)  # Precio de compra
    sale_price = db.Column(db.Float, nullable=False, default=0.0)      # Precio de venta
    stock = db.Column(db.Integer, default=0)
    min_stock = db.Column(db.Integer, default=5)
    is_active = db.Column(db.Boolean, default=True)
    category_id = db.Column(db.Integer, db.ForeignKey('category.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    movements = db.relationship('ProductMovement', backref='product', lazy='dynamic')

class Notification(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)  # destinatario
    title = db.Column(db.String(200), nullable=False)
    message = db.Column(db.Text)
    link = db.Column(db.String(300))  # URL relativa opcional
    is_read = db.Column(db.Boolean, default=False)
    type = db.Column(db.String(30), default='info')  # info, cita, venta, alerta
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    user = db.relationship('User', backref='notifications')

class ProductMovement(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey('product.id'), nullable=False)
    movement_type = db.Column(db.String(20), nullable=False)  # entrada, salida, ajuste
    quantity = db.Column(db.Integer, nullable=False)
    unit_cost = db.Column(db.Float, default=0.0)   # Costo unitario (para entradas)
    unit_price = db.Column(db.Float, default=0.0)  # Precio unitario (para salidas)
    total = db.Column(db.Float, default=0.0)
    notes = db.Column(db.Text)
    date = db.Column(db.DateTime, default=datetime.utcnow)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    transaction_id = db.Column(db.Integer, db.ForeignKey('transaction.id'), nullable=True)
    user = db.relationship('User', backref='movements')

class Service(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    description = db.Column(db.Text)
    price = db.Column(db.Float, nullable=False, default=0.0)
    duration_minutes = db.Column(db.Integer, default=30)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Transaction(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    type = db.Column(db.String(30), nullable=False)  # venta, gasto, compra
    amount = db.Column(db.Float, nullable=False)  # positivo ingreso, negativo egreso
    description = db.Column(db.Text)
    payment_method = db.Column(db.String(30), default='efectivo')  # efectivo, tarjeta, transferencia
    date = db.Column(db.DateTime, default=datetime.utcnow)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))  # quien registró
    client_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    user = db.relationship('User', foreign_keys=[user_id], backref='transactions_registered')
    client = db.relationship('User', foreign_keys=[client_id], backref='transactions_as_client')
    items = db.relationship('SaleItem', backref='transaction', lazy='dynamic')
    movements = db.relationship('ProductMovement', backref='transaction', lazy='dynamic')

class SaleItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    transaction_id = db.Column(db.Integer, db.ForeignKey('transaction.id'), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey('product.id'), nullable=True)
    service_id = db.Column(db.Integer, db.ForeignKey('service.id'), nullable=True)
    quantity = db.Column(db.Integer, default=1)
    unit_price = db.Column(db.Float, nullable=False)
    subtotal = db.Column(db.Float, nullable=False)
    product = db.relationship('Product')
    service = db.relationship('Service')

class BusinessHour(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    day_of_week = db.Column(db.Integer, nullable=False)  # 0=Lunes ... 6=Domingo
    open_time = db.Column(db.String(5))  # HH:MM
    close_time = db.Column(db.String(5))
    is_closed = db.Column(db.Boolean, default=False)

class Appointment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    client_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    service_id = db.Column(db.Integer, db.ForeignKey('service.id'), nullable=True)
    date = db.Column(db.Date, nullable=False)
    time = db.Column(db.String(5), nullable=False)  # HH:MM
    notes = db.Column(db.Text)
    status = db.Column(db.String(20), default='pendiente')  # pendiente, confirmada, cancelada, completada
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    client = db.relationship('User', backref='appointments')
    service = db.relationship('Service')

@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or current_user.role != 'admin':
            flash('Acceso denegado. Se requieren privilegios de administrador.', 'danger')
            return redirect(url_for('index'))
        return f(*args, **kwargs)
    return decorated_function

def create_notification(user_id, title, message='', link=None, ntype='info'):
    """Crea una notificación para un usuario."""
    n = Notification(user_id=user_id, title=title, message=message, link=link, type=ntype)
    db.session.add(n)
    return n

@app.context_processor
def inject_notifications():
    if current_user.is_authenticated:
        unread = Notification.query.filter_by(user_id=current_user.id, is_read=False).count()
        recent = Notification.query.filter_by(user_id=current_user.id).order_by(
            Notification.created_at.desc()).limit(8).all()
        return dict(unread_notifications=unread, recent_notifications=recent)
    return dict(unread_notifications=0, recent_notifications=[])

# ==================== RUTAS ====================

@app.route('/')
def index():
    products = Product.query.filter_by(is_active=True).order_by(Product.name).limit(6).all()
    services = Service.query.filter_by(is_active=True).order_by(Service.name).limit(6).all()
    hours = BusinessHour.query.order_by(BusinessHour.day_of_week).all()
    days = ['Lunes', 'Martes', 'Miércoles', 'Jueves', 'Viernes', 'Sábado', 'Domingo']
    return render_template('index.html', products=products, services=services, hours=hours, days=days)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        user = User.query.filter_by(username=username).first()
        if user and user.check_password(password):
            login_user(user)
            flash(f'¡Bienvenido/a, {user.name}!', 'success')
            next_page = request.args.get('next')
            if user.role == 'admin':
                return redirect(next_page or url_for('admin_dashboard'))
            return redirect(next_page or url_for('client_portal'))
        flash('Usuario o contraseña incorrectos.', 'danger')
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    if request.method == 'POST':
        username = request.form.get('username')
        email = request.form.get('email')
        name = request.form.get('name')
        phone = request.form.get('phone')
        password = request.form.get('password')
        if User.query.filter_by(username=username).first():
            flash('El nombre de usuario ya existe.', 'danger')
            return render_template('register.html')
        if User.query.filter_by(email=email).first():
            flash('El correo ya está registrado.', 'danger')
            return render_template('register.html')
        user = User(username=username, email=email, name=name, phone=phone, role='client')
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        flash('Registro exitoso. Ya puedes iniciar sesión.', 'success')
        return redirect(url_for('login'))
    return render_template('register.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('Sesión cerrada correctamente.', 'info')
    return redirect(url_for('index'))

# ---------- ADMIN ----------

@app.route('/admin')
@login_required
@admin_required
def admin_dashboard():
    total_products = Product.query.filter_by(is_active=True).count()
    low_stock = Product.query.filter(Product.stock <= Product.min_stock, Product.is_active == True).count()
    today = date.today()
    ventas_hoy = db.session.query(db.func.sum(Transaction.amount)).filter(
        Transaction.type == 'venta',
        db.func.date(Transaction.date) == today
    ).scalar() or 0
    gastos_hoy = db.session.query(db.func.sum(Transaction.amount)).filter(
        Transaction.type == 'gasto',
        db.func.date(Transaction.date) == today
    ).scalar() or 0
    citas_pendientes = Appointment.query.filter_by(status='pendiente').count()
    recent_tx = Transaction.query.order_by(Transaction.date.desc()).limit(8).all()
    return render_template('admin/dashboard.html',
                           total_products=total_products,
                           low_stock=low_stock,
                           ventas_hoy=ventas_hoy,
                           gastos_hoy=abs(gastos_hoy),
                           citas_pendientes=citas_pendientes,
                           recent_tx=recent_tx)

# --- PRODUCTOS / ALMACÉN ---

@app.route('/admin/productos')
@login_required
@admin_required
def admin_productos():
    cat_id = request.args.get('categoria', type=int)
    query = Product.query
    if cat_id:
        query = query.filter_by(category_id=cat_id)
    products = query.order_by(Product.name).all()
    categories = Category.query.order_by(Category.name).all()
    return render_template('admin/productos.html', products=products, categories=categories, cat_id=cat_id)

@app.route('/admin/productos/nuevo', methods=['GET', 'POST'])
@login_required
@admin_required
def producto_nuevo():
    categories = Category.query.order_by(Category.name).all()
    if request.method == 'POST':
        cat_id = request.form.get('category_id') or None
        p = Product(
            name=request.form['name'],
            description=request.form.get('description', ''),
            purchase_price=float(request.form['purchase_price'] or 0),
            sale_price=float(request.form['sale_price'] or 0),
            stock=int(request.form.get('stock', 0) or 0),
            min_stock=int(request.form.get('min_stock', 5) or 5),
            category_id=int(cat_id) if cat_id else None
        )
        db.session.add(p)
        db.session.commit()
        if p.stock > 0:
            mov = ProductMovement(
                product_id=p.id,
                movement_type='entrada',
                quantity=p.stock,
                unit_cost=p.purchase_price,
                total=p.stock * p.purchase_price,
                notes='Stock inicial',
                user_id=current_user.id
            )
            db.session.add(mov)
            db.session.commit()
        flash('Producto creado correctamente.', 'success')
        return redirect(url_for('admin_productos'))
    return render_template('admin/producto_form.html', product=None, categories=categories)

@app.route('/admin/productos/<int:id>/editar', methods=['GET', 'POST'])
@login_required
@admin_required
def producto_editar(id):
    product = Product.query.get_or_404(id)
    categories = Category.query.order_by(Category.name).all()
    if request.method == 'POST':
        product.name = request.form['name']
        product.description = request.form.get('description', '')
        product.purchase_price = float(request.form['purchase_price'] or 0)
        product.sale_price = float(request.form['sale_price'] or 0)
        product.min_stock = int(request.form.get('min_stock', 5) or 5)
        product.is_active = 'is_active' in request.form
        cat_id = request.form.get('category_id') or None
        product.category_id = int(cat_id) if cat_id else None
        db.session.commit()
        flash('Producto actualizado.', 'success')
        return redirect(url_for('admin_productos'))
    return render_template('admin/producto_form.html', product=product, categories=categories)

@app.route('/admin/productos/<int:id>/entrada', methods=['GET', 'POST'])
@login_required
@admin_required
def producto_entrada(id):
    product = Product.query.get_or_404(id)
    if request.method == 'POST':
        qty = int(request.form['quantity'])
        cost = float(request.form.get('unit_cost') or product.purchase_price)
        notes = request.form.get('notes', '')
        if qty <= 0:
            flash('La cantidad debe ser positiva.', 'danger')
            return redirect(url_for('producto_entrada', id=id))
        product.stock += qty
        # Actualizar precio de compra promedio simple o el último
        product.purchase_price = cost
        mov = ProductMovement(
            product_id=product.id,
            movement_type='entrada',
            quantity=qty,
            unit_cost=cost,
            total=qty * cost,
            notes=notes or 'Compra / entrada de mercancía',
            user_id=current_user.id
        )
        # Crear transacción de compra (egreso)
        tx = Transaction(
            type='compra',
            amount=-(qty * cost),
            description=f'Compra de {qty} x {product.name}',
            payment_method=request.form.get('payment_method', 'efectivo'),
            user_id=current_user.id
        )
        db.session.add(tx)
        db.session.flush()
        mov.transaction_id = tx.id
        db.session.add(mov)
        db.session.commit()
        flash(f'Entrada de {qty} unidades registrada. Stock actual: {product.stock}', 'success')
        return redirect(url_for('admin_productos'))
    return render_template('admin/producto_entrada.html', product=product)

@app.route('/admin/productos/<int:id>/movimientos')
@login_required
@admin_required
def producto_movimientos(id):
    product = Product.query.get_or_404(id)
    movements = ProductMovement.query.filter_by(product_id=id).order_by(ProductMovement.date.desc()).all()
    return render_template('admin/producto_movimientos.html', product=product, movements=movements)

# --- SERVICIOS ---

@app.route('/admin/servicios')
@login_required
@admin_required
def admin_servicios():
    services = Service.query.order_by(Service.name).all()
    return render_template('admin/servicios.html', services=services)

@app.route('/admin/servicios/nuevo', methods=['GET', 'POST'])
@login_required
@admin_required
def servicio_nuevo():
    if request.method == 'POST':
        s = Service(
            name=request.form['name'],
            description=request.form.get('description', ''),
            price=float(request.form['price'] or 0),
            duration_minutes=int(request.form.get('duration_minutes', 30) or 30)
        )
        db.session.add(s)
        db.session.commit()
        flash('Servicio creado.', 'success')
        return redirect(url_for('admin_servicios'))
    return render_template('admin/servicio_form.html', service=None)

@app.route('/admin/servicios/<int:id>/editar', methods=['GET', 'POST'])
@login_required
@admin_required
def servicio_editar(id):
    service = Service.query.get_or_404(id)
    if request.method == 'POST':
        service.name = request.form['name']
        service.description = request.form.get('description', '')
        service.price = float(request.form['price'] or 0)
        service.duration_minutes = int(request.form.get('duration_minutes', 30) or 30)
        service.is_active = 'is_active' in request.form
        db.session.commit()
        flash('Servicio actualizado.', 'success')
        return redirect(url_for('admin_servicios'))
    return render_template('admin/servicio_form.html', service=service)

# --- CAJA REGISTRADORA ---

@app.route('/admin/caja')
@login_required
@admin_required
def admin_caja():
    today = date.today()
    tx_hoy = Transaction.query.filter(db.func.date(Transaction.date) == today).order_by(Transaction.date.desc()).all()
    ingresos = sum(t.amount for t in tx_hoy if t.amount > 0)
    egresos = sum(abs(t.amount) for t in tx_hoy if t.amount < 0)
    return render_template('admin/caja.html', transactions=tx_hoy, ingresos=ingresos, egresos=egresos, today=today)

@app.route('/admin/caja/venta', methods=['GET', 'POST'])
@login_required
@admin_required
def caja_venta():
    products = Product.query.filter_by(is_active=True).filter(Product.stock > 0).order_by(Product.name).all()
    services = Service.query.filter_by(is_active=True).order_by(Service.name).all()
    clients = User.query.filter_by(role='client').order_by(User.name).all()
    if request.method == 'POST':
        items_data = request.form.getlist('item_type')
        item_ids = request.form.getlist('item_id')
        quantities = request.form.getlist('quantity')
        payment_method = request.form.get('payment_method', 'efectivo')
        client_id = request.form.get('client_id') or None
        notes = request.form.get('notes', '')

        if not items_data:
            flash('Debes agregar al menos un producto o servicio.', 'danger')
            return redirect(url_for('caja_venta'))

        total = 0.0
        sale_items = []
        for i, itype in enumerate(items_data):
            qty = int(quantities[i])
            if qty <= 0:
                continue
            if itype == 'product':
                prod = Product.query.get(int(item_ids[i]))
                if not prod or prod.stock < qty:
                    flash(f'Stock insuficiente para {prod.name if prod else "producto"}.', 'danger')
                    return redirect(url_for('caja_venta'))
                sub = qty * prod.sale_price
                total += sub
                sale_items.append({'type': 'product', 'obj': prod, 'qty': qty, 'price': prod.sale_price, 'sub': sub})
            else:
                serv = Service.query.get(int(item_ids[i]))
                if not serv:
                    continue
                sub = qty * serv.price
                total += sub
                sale_items.append({'type': 'service', 'obj': serv, 'qty': qty, 'price': serv.price, 'sub': sub})

        if total <= 0:
            flash('Total de venta inválido.', 'danger')
            return redirect(url_for('caja_venta'))

        tx = Transaction(
            type='venta',
            amount=total,
            description=notes or 'Venta de productos/servicios',
            payment_method=payment_method,
            user_id=current_user.id,
            client_id=int(client_id) if client_id else None
        )
        db.session.add(tx)
        db.session.flush()

        for item in sale_items:
            if item['type'] == 'product':
                prod = item['obj']
                prod.stock -= item['qty']
                si = SaleItem(transaction_id=tx.id, product_id=prod.id, quantity=item['qty'],
                              unit_price=item['price'], subtotal=item['sub'])
                db.session.add(si)
                mov = ProductMovement(
                    product_id=prod.id,
                    movement_type='salida',
                    quantity=item['qty'],
                    unit_price=item['price'],
                    total=item['sub'],
                    notes=f'Venta #{tx.id}',
                    user_id=current_user.id,
                    transaction_id=tx.id
                )
                db.session.add(mov)
            else:
                serv = item['obj']
                si = SaleItem(transaction_id=tx.id, service_id=serv.id, quantity=item['qty'],
                              unit_price=item['price'], subtotal=item['sub'])
                db.session.add(si)

        db.session.commit()
        flash(f'Venta registrada por ${total:.2f}', 'success')
        return redirect(url_for('ticket_venta', id=tx.id))

    return render_template('admin/caja_venta.html', products=products, services=services, clients=clients)

@app.route('/admin/caja/gasto', methods=['GET', 'POST'])
@login_required
@admin_required
def caja_gasto():
    if request.method == 'POST':
        amount = float(request.form['amount'])
        description = request.form['description']
        payment_method = request.form.get('payment_method', 'efectivo')
        if amount <= 0:
            flash('El monto debe ser positivo.', 'danger')
            return redirect(url_for('caja_gasto'))
        tx = Transaction(
            type='gasto',
            amount=-amount,
            description=description,
            payment_method=payment_method,
            user_id=current_user.id
        )
        db.session.add(tx)
        db.session.commit()
        flash(f'Gasto de ${amount:.2f} registrado.', 'success')
        return redirect(url_for('admin_caja'))
    return render_template('admin/caja_gasto.html')

@app.route('/admin/caja/historial')
@login_required
@admin_required
def caja_historial():
    page = request.args.get('page', 1, type=int)
    tipo = request.args.get('tipo', '')
    query = Transaction.query
    if tipo:
        query = query.filter_by(type=tipo)
    transactions = query.order_by(Transaction.date.desc()).paginate(page=page, per_page=20, error_out=False)
    return render_template('admin/caja_historial.html', transactions=transactions, tipo=tipo)

# --- HORARIOS ---

@app.route('/admin/horarios', methods=['GET', 'POST'])
@login_required
@admin_required
def admin_horarios():
    days = ['Lunes', 'Martes', 'Miércoles', 'Jueves', 'Viernes', 'Sábado', 'Domingo']
    if request.method == 'POST':
        for i in range(7):
            bh = BusinessHour.query.filter_by(day_of_week=i).first()
            if not bh:
                bh = BusinessHour(day_of_week=i)
                db.session.add(bh)
            is_closed = f'closed_{i}' in request.form
            bh.is_closed = is_closed
            if not is_closed:
                bh.open_time = request.form.get(f'open_{i}', '09:00')
                bh.close_time = request.form.get(f'close_{i}', '18:00')
            else:
                bh.open_time = None
                bh.close_time = None
        db.session.commit()
        flash('Horarios actualizados.', 'success')
        return redirect(url_for('admin_horarios'))
    hours = {h.day_of_week: h for h in BusinessHour.query.all()}
    return render_template('admin/horarios.html', days=days, hours=hours)

# --- CITAS (admin) ---

@app.route('/admin/citas')
@login_required
@admin_required
def admin_citas():
    status = request.args.get('status', '')
    query = Appointment.query
    if status:
        query = query.filter_by(status=status)
    appointments = query.order_by(Appointment.date.desc(), Appointment.time).all()
    return render_template('admin/citas.html', appointments=appointments, status=status)

@app.route('/admin/citas/<int:id>/estado', methods=['POST'])
@login_required
@admin_required
def cita_estado(id):
    appt = Appointment.query.get_or_404(id)
    new_status = request.form.get('status')
    if new_status in ['pendiente', 'confirmada', 'cancelada', 'completada']:
        old = appt.status
        appt.status = new_status
        # Notificar al cliente del cambio de estado
        if old != new_status and appt.client_id:
            status_labels = {
                'pendiente': 'Pendiente',
                'confirmada': 'Confirmada',
                'cancelada': 'Cancelada',
                'completada': 'Completada'
            }
            create_notification(
                appt.client_id,
                f'Tu cita del {appt.date.strftime("%d/%m/%Y")} a las {appt.time} fue marcada como: {status_labels.get(new_status, new_status)}',
                f'Servicio: {appt.service.name if appt.service else "Visita general"}',
                link=url_for('client_portal'),
                ntype='cita'
            )
        db.session.commit()
        flash('Estado de la cita actualizado.', 'success')
    return redirect(url_for('admin_citas'))

# ---------- CLIENTE ----------

@app.route('/cliente')
@login_required
def client_portal():
    if current_user.role == 'admin':
        return redirect(url_for('admin_dashboard'))
    products = Product.query.filter_by(is_active=True).order_by(Product.name).all()
    services = Service.query.filter_by(is_active=True).order_by(Service.name).all()
    hours = BusinessHour.query.order_by(BusinessHour.day_of_week).all()
    days = ['Lunes', 'Martes', 'Miércoles', 'Jueves', 'Viernes', 'Sábado', 'Domingo']
    my_appointments = Appointment.query.filter_by(client_id=current_user.id).order_by(
        Appointment.date.desc(), Appointment.time).limit(10).all()
    return render_template('client/portal.html', products=products, services=services,
                           hours=hours, days=days, appointments=my_appointments)

@app.route('/cliente/cita', methods=['GET', 'POST'])
@login_required
def client_cita():
    if current_user.role == 'admin':
        return redirect(url_for('admin_citas'))
    services = Service.query.filter_by(is_active=True).order_by(Service.name).all()
    hours = BusinessHour.query.order_by(BusinessHour.day_of_week).all()
    if request.method == 'POST':
        service_id = request.form.get('service_id') or None
        fecha = request.form.get('date')
        hora = request.form.get('time')
        notes = request.form.get('notes', '')
        if not fecha or not hora:
            flash('Fecha y hora son obligatorias.', 'danger')
            return redirect(url_for('client_cita'))
        appt = Appointment(
            client_id=current_user.id,
            service_id=int(service_id) if service_id else None,
            date=datetime.strptime(fecha, '%Y-%m-%d').date(),
            time=hora,
            notes=notes,
            status='pendiente'
        )
        db.session.add(appt)
        db.session.flush()
        # Notificar a todos los admins
        admins = User.query.filter_by(role='admin').all()
        serv_name = appt.service.name if appt.service else 'Visita general'
        for admin in admins:
            create_notification(
                admin.id,
                f'Nueva cita de {current_user.name}',
                f'{appt.date.strftime("%d/%m/%Y")} a las {appt.time} · {serv_name}',
                link=url_for('admin_citas'),
                ntype='cita'
            )
        db.session.commit()
        flash('Cita solicitada correctamente. Te contactaremos para confirmar.', 'success')
        return redirect(url_for('client_portal'))
    return render_template('client/cita.html', services=services, hours=hours)

@app.route('/catalogo')
def catalogo():
    cat_id = request.args.get('categoria', type=int)
    query = Product.query.filter_by(is_active=True)
    if cat_id:
        query = query.filter_by(category_id=cat_id)
    products = query.order_by(Product.name).all()
    services = Service.query.filter_by(is_active=True).order_by(Service.name).all()
    categories = Category.query.order_by(Category.name).all()
    return render_template('catalogo.html', products=products, services=services,
                           categories=categories, cat_id=cat_id)

# ---------- CATEGORÍAS ----------

@app.route('/admin/categorias')
@login_required
@admin_required
def admin_categorias():
    categories = Category.query.order_by(Category.name).all()
    return render_template('admin/categorias.html', categories=categories)

@app.route('/admin/categorias/nueva', methods=['GET', 'POST'])
@login_required
@admin_required
def categoria_nueva():
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        if not name:
            flash('El nombre es obligatorio.', 'danger')
            return redirect(url_for('categoria_nueva'))
        if Category.query.filter_by(name=name).first():
            flash('Ya existe una categoría con ese nombre.', 'danger')
            return redirect(url_for('categoria_nueva'))
        c = Category(name=name, description=request.form.get('description', ''))
        db.session.add(c)
        db.session.commit()
        flash('Categoría creada.', 'success')
        return redirect(url_for('admin_categorias'))
    return render_template('admin/categoria_form.html', category=None)

@app.route('/admin/categorias/<int:id>/editar', methods=['GET', 'POST'])
@login_required
@admin_required
def categoria_editar(id):
    category = Category.query.get_or_404(id)
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        if not name:
            flash('El nombre es obligatorio.', 'danger')
            return redirect(url_for('categoria_editar', id=id))
        existing = Category.query.filter(Category.name == name, Category.id != id).first()
        if existing:
            flash('Ya existe otra categoría con ese nombre.', 'danger')
            return redirect(url_for('categoria_editar', id=id))
        category.name = name
        category.description = request.form.get('description', '')
        db.session.commit()
        flash('Categoría actualizada.', 'success')
        return redirect(url_for('admin_categorias'))
    return render_template('admin/categoria_form.html', category=category)

@app.route('/admin/categorias/<int:id>/eliminar', methods=['POST'])
@login_required
@admin_required
def categoria_eliminar(id):
    category = Category.query.get_or_404(id)
    # Desasociar productos
    Product.query.filter_by(category_id=id).update({'category_id': None})
    db.session.delete(category)
    db.session.commit()
    flash('Categoría eliminada. Los productos quedaron sin categoría.', 'info')
    return redirect(url_for('admin_categorias'))

# ---------- REPORTE DE GANANCIAS ----------

@app.route('/admin/ganancias')
@login_required
@admin_required
def admin_ganancias():
    desde = request.args.get('desde', '')
    hasta = request.args.get('hasta', '')
    # Ventas de productos: usar SaleItem + Product para calcular margen
    query = db.session.query(
        SaleItem,
        Product,
        Transaction
    ).join(Product, SaleItem.product_id == Product.id)\
     .join(Transaction, SaleItem.transaction_id == Transaction.id)\
     .filter(Transaction.type == 'venta', SaleItem.product_id.isnot(None))

    if desde:
        try:
            d = datetime.strptime(desde, '%Y-%m-%d').date()
            query = query.filter(db.func.date(Transaction.date) >= d)
        except ValueError:
            pass
    if hasta:
        try:
            h = datetime.strptime(hasta, '%Y-%m-%d').date()
            query = query.filter(db.func.date(Transaction.date) <= h)
        except ValueError:
            pass

    rows = query.order_by(Transaction.date.desc()).all()

    detalle = []
    total_ventas = 0.0
    total_costo = 0.0
    total_ganancia = 0.0
    por_producto = {}

    for si, prod, tx in rows:
        costo = si.quantity * (prod.purchase_price or 0)
        venta = si.subtotal
        ganancia = venta - costo
        margen = (ganancia / venta * 100) if venta > 0 else 0
        total_ventas += venta
        total_costo += costo
        total_ganancia += ganancia
        detalle.append({
            'fecha': tx.date,
            'producto': prod.name,
            'categoria': prod.category.name if prod.category else '—',
            'cantidad': si.quantity,
            'p_compra': prod.purchase_price,
            'p_venta': si.unit_price,
            'venta': venta,
            'costo': costo,
            'ganancia': ganancia,
            'margen': margen,
            'tx_id': tx.id
        })
        key = prod.id
        if key not in por_producto:
            por_producto[key] = {
                'nombre': prod.name,
                'categoria': prod.category.name if prod.category else '—',
                'cantidad': 0,
                'venta': 0.0,
                'costo': 0.0,
                'ganancia': 0.0
            }
        por_producto[key]['cantidad'] += si.quantity
        por_producto[key]['venta'] += venta
        por_producto[key]['costo'] += costo
        por_producto[key]['ganancia'] += ganancia

    resumen_productos = sorted(por_producto.values(), key=lambda x: x['ganancia'], reverse=True)
    margen_global = (total_ganancia / total_ventas * 100) if total_ventas > 0 else 0

    # También sumar servicios (ganancia = 100% del precio, sin costo de almacén)
    serv_query = db.session.query(SaleItem, Service, Transaction)\
        .join(Service, SaleItem.service_id == Service.id)\
        .join(Transaction, SaleItem.transaction_id == Transaction.id)\
        .filter(Transaction.type == 'venta', SaleItem.service_id.isnot(None))
    if desde:
        try:
            d = datetime.strptime(desde, '%Y-%m-%d').date()
            serv_query = serv_query.filter(db.func.date(Transaction.date) >= d)
        except ValueError:
            pass
    if hasta:
        try:
            h = datetime.strptime(hasta, '%Y-%m-%d').date()
            serv_query = serv_query.filter(db.func.date(Transaction.date) <= h)
        except ValueError:
            pass
    servicios_rows = serv_query.all()
    total_servicios = sum(si.subtotal for si, s, tx in servicios_rows)

    return render_template('admin/ganancias.html',
                           detalle=detalle,
                           resumen_productos=resumen_productos,
                           total_ventas=total_ventas,
                           total_costo=total_costo,
                           total_ganancia=total_ganancia,
                           margen_global=margen_global,
                           total_servicios=total_servicios,
                           desde=desde,
                           hasta=hasta)

# ---------- TICKET / IMPRESIÓN ----------

@app.route('/admin/ticket/<int:id>')
@login_required
@admin_required
def ticket_venta(id):
    tx = Transaction.query.get_or_404(id)
    if tx.type != 'venta':
        flash('Solo se pueden imprimir tickets de ventas.', 'warning')
        return redirect(url_for('admin_caja'))
    items = SaleItem.query.filter_by(transaction_id=id).all()
    return render_template('admin/ticket.html', tx=tx, items=items)

# ---------- NOTIFICACIONES ----------

@app.route('/notificaciones')
@login_required
def notificaciones():
    notifs = Notification.query.filter_by(user_id=current_user.id)\
        .order_by(Notification.created_at.desc()).limit(50).all()
    return render_template('notificaciones.html', notifs=notifs)

@app.route('/notificaciones/leer/<int:id>', methods=['POST'])
@login_required
def notificacion_leer(id):
    n = Notification.query.filter_by(id=id, user_id=current_user.id).first_or_404()
    n.is_read = True
    db.session.commit()
    if n.link:
        return redirect(n.link)
    return redirect(url_for('notificaciones'))

@app.route('/notificaciones/leer-todas', methods=['POST'])
@login_required
def notificaciones_leer_todas():
    Notification.query.filter_by(user_id=current_user.id, is_read=False)\
        .update({'is_read': True})
    db.session.commit()
    flash('Todas las notificaciones marcadas como leídas.', 'success')
    return redirect(request.referrer or url_for('notificaciones'))

# ==================== INICIALIZACIÓN ====================

def init_db():
    """Crea tablas y datos iniciales. Seguro llamar varias veces."""
    with app.app_context():
        db.create_all()
        # Migración category_id solo si la tabla product ya existe
        try:
            from sqlalchemy import text, inspect
            insp = inspect(db.engine)
            if 'product' in insp.get_table_names():
                cols = [c['name'] for c in insp.get_columns('product')]
                if 'category_id' not in cols:
                    db.session.execute(text(
                        'ALTER TABLE product ADD COLUMN category_id INTEGER REFERENCES category(id)'
                    ))
                    db.session.commit()
                    print('Columna category_id agregada a product.')
        except Exception as e:
            print('Migración category_id:', e)
            db.session.rollback()

        # Admin y datos de ejemplo solo si no hay usuarios
        if not User.query.filter_by(username='admin').first():
            admin = User(username='admin', email='admin@negocio.com', name='Administrador', role='admin')
            admin.set_password('admin123')
            db.session.add(admin)
            client = User(username='cliente', email='cliente@test.com', name='Cliente Demo', role='client', phone='555-1234')
            client.set_password('cliente123')
            db.session.add(client)
            for i in range(7):
                bh = BusinessHour(day_of_week=i)
                if i < 5:
                    bh.open_time = '09:00'
                    bh.close_time = '18:00'
                    bh.is_closed = False
                elif i == 5:
                    bh.open_time = '09:00'
                    bh.close_time = '14:00'
                    bh.is_closed = False
                else:
                    bh.is_closed = True
                db.session.add(bh)

            cat_gen = Category(name='General', description='Productos varios')
            cat_elec = Category(name='Electrónica', description='Dispositivos y accesorios')
            cat_hogar = Category(name='Hogar', description='Artículos para el hogar')
            db.session.add_all([cat_gen, cat_elec, cat_hogar])
            db.session.flush()

            for p in [
                Product(name='Producto A', description='Producto de ejemplo A', purchase_price=10.0, sale_price=18.0, stock=50, category_id=cat_gen.id),
                Product(name='Producto B', description='Producto de ejemplo B', purchase_price=25.0, sale_price=40.0, stock=30, category_id=cat_elec.id),
                Product(name='Producto C', description='Producto de ejemplo C', purchase_price=5.0, sale_price=12.0, stock=100, category_id=cat_hogar.id),
            ]:
                db.session.add(p)
            for s in [
                Service(name='Consulta general', description='Atención personalizada', price=25.0, duration_minutes=30),
                Service(name='Servicio premium', description='Servicio completo de alta calidad', price=50.0, duration_minutes=60),
                Service(name='Reparación rápida', description='Reparación exprés', price=35.0, duration_minutes=45),
            ]:
                db.session.add(s)
            db.session.commit()
            print('Base de datos inicializada. Admin: admin/admin123  Cliente: cliente/cliente123')
        else:
            if Category.query.count() == 0:
                for name, desc in [('General', 'Productos varios'), ('Electrónica', 'Dispositivos'), ('Hogar', 'Artículos del hogar')]:
                    db.session.add(Category(name=name, description=desc))
                db.session.commit()

# Asegurar tablas en cada arranque (Gunicorn / Render)
_db_ready = False

@app.before_request
def _ensure_db():
    global _db_ready
    if not _db_ready:
        try:
            init_db()
        except Exception as e:
            print('Error init_db:', e)
        _db_ready = True

# También al importar el módulo
try:
    init_db()
    _db_ready = True
except Exception as e:
    print('Aviso al inicializar BD:', e)

if __name__ == '__main__':

    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
