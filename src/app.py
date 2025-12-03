# app.py
from flask import Flask, request, jsonify, send_from_directory, g
from flask_cors import CORS
import sqlite3
import os
from datetime import datetime
import json

app = Flask(__name__)
CORS(app)

# Конфигурация
DATABASE = 'ecostore.db'
DEBUG = True

def get_db():
    """Получение соединения с базой данных"""
    db = getattr(g, '_database', None)
    if db is None:
        db = g._database = sqlite3.connect(DATABASE)
        db.row_factory = sqlite3.Row
    return db

@app.teardown_appcontext
def close_connection(exception):
    """Закрытие соединения с базой данных"""
    db = getattr(g, '_database', None)
    if db is not None:
        db.close()

def init_db():
    """Инициализация базы данных"""
    with app.app_context():
        db = get_db()
        
        # Создание таблиц
        with app.open_resource('schema.sql', mode='r') as f:
            db.cursor().executescript(f.read())
        db.commit()
        
        # Добавление тестовых данных
        insert_sample_data()

def insert_sample_data():
    """Добавление тестовых данных"""
    db = get_db()
    
    # Проверяем, есть ли уже данные
    if db.execute('SELECT COUNT(*) FROM products').fetchone()[0] == 0:
        # Добавляем продукты
        products = [
            (1, "Шампунь веганский для чувствительной кожи", 650, 800, "cosmetics", "EcoBeauty", "vegan,organic", 4.5, 23, "🚿", "Натуральный шампунь без SLS и парабенов. Подходит для ежедневного использования.", 1, 0, '{"composition": "Вода, кокосовое масло, алоэ вера, экстракт ромашки", "weight": "250 мл", "country": "Россия", "expiration": "24 месяца"}'),
            (2, "Многоразовая стеклянная бутылка 1л", 1200, 1500, "bottles", "EcoBottle", "vegan,biodegradable", 4.2, 45, "💧", "Экологичная бутылка из боросиликатного стекла с силиконовым чехлом.", 1, 1, '{"composition": "Боросиликатное стекло, силикон", "weight": "450 г", "country": "Германия", "expiration": "Неограничен"}'),
            (3, "Органический протеиновый батончик", 150, None, "food", "HealthFood", "vegan,gluten-free,organic", 4.7, 89, "🍫", "Батончик с высоким содержанием белка из органических ингредиентов.", 1, 1, '{"composition": "Овсяные хлопья, протеин гороховый, финики, какао", "weight": "60 г", "country": "Россия", "expiration": "12 месяцев"}'),
            (4, "Бамбуковая зубная щетка", 350, None, "home", "EcoHome", "biodegradable", 4.0, 34, "🪥", "Экологичная зубная щетка из бамбука с угольной щетиной.", 1, 0, '{"composition": "Бамбук, нейлоновая щетина с углем", "weight": "25 г", "country": "Китай", "expiration": "Неограничен"}'),
            (5, "Веганский крем для лица", 890, 1100, "cosmetics", "PureSkin", "vegan,organic", 4.8, 67, "🧴", "Питательный крем с органическими маслами для всех типов кожи.", 1, 1, '{"composition": "Масло ши, масло жожоба, гиалуроновая кислота, витамин E", "weight": "50 мл", "country": "Франция", "expiration": "18 месяцев"}'),
            (6, "Эко-сумка для покупок", 450, None, "home", "EcoBag", "biodegradable", 4.3, 56, "🛍️", "Прочная сумка из органического хлопка с принтом.", 1, 0, '{"composition": "100% органический хлопок", "weight": "200 г", "country": "Индия", "expiration": "Неограничен"}'),
            (7, "Безглютеновые хлебцы", 280, None, "food", "HealthFood", "gluten-free,vegan", 4.1, 42, "🍞", "Хрустящие хлебцы из цельного зерна без глютена.", 1, 0, '{"composition": "Рис, гречка, семена льна, соль морская", "weight": "150 г", "country": "Россия", "expiration": "9 месяцев"}'),
            (8, "Набор эко-посуды", 2300, 2900, "home", "EcoHome", "biodegradable", 4.6, 28, "🍽️", "Полный набор посуды из бамбука для повседневного использования.", 1, 1, '{"composition": "Бамбуковое волокно, кукурузный крахмал", "weight": "1200 г", "country": "Вьетнам", "expiration": "Неограничен"}')
        ]
        
        db.executemany('''
            INSERT OR REPLACE INTO products 
            (id, name, price, original_price, category, brand, features, rating, reviews, image, description, in_stock, is_new, details)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', products)
        
        # Добавляем посты блога
        blog_posts = [
            (1, "Как начать экологичный образ жизни", "Простые шаги для перехода к sustainable lifestyle", "Полное руководство по переходу на экологичный образ жизни...", "2024-01-15", "🌱", "Эко-эксперт", "5 мин"),
            (2, "Топ 5 веганских продуктов", "Лучшие продукты для веганского питания", "Обзор самых полезных и вкусных веганских продуктов...", "2024-01-10", "🥗", "Шеф-повар", "7 мин")
        ]
        
        db.executemany('''
            INSERT OR REPLACE INTO blog_posts 
            (id, title, excerpt, content, date, image, author, read_time)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', blog_posts)
        
        db.commit()

# API endpoints для продуктов
@app.route('/api/users/register', methods=['POST'])
def register_user():
    """Регистрация нового пользователя"""
    try:
        data = request.json
        name = data.get('name')
        email = data.get('email')
        password = data.get('password')
        
        if not name or not email or not password:
            return jsonify({'error': 'Все поля обязательны'}), 400
        
        db = get_db()
        
        # Проверяем, есть ли уже пользователь с таким email
        existing_user = db.execute('SELECT * FROM users WHERE email = ?', (email,)).fetchone()
        if existing_user:
            return jsonify({'error': 'Пользователь с таким email уже существует'}), 400
        
        # Создаем нового пользователя
        user_id = db.execute('''
            INSERT INTO users (name, email, bonuses) 
            VALUES (?, ?, ?)
        ''', (name, email, 100)).lastrowid
        
        db.commit()
        
        return jsonify({
            'success': True, 
            'user_id': user_id,
            'name': name,
            'email': email
        })
    
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/users/login', methods=['POST'])
def login_user():
    """Вход пользователя"""
    try:
        data = request.json
        email = data.get('email')
        password = data.get('password')
        
        if not email or not password:
            return jsonify({'error': 'Email и пароль обязательны'}), 400
        
        db = get_db()
        
        # Ищем пользователя (в реальном приложении нужно проверять пароль)
        user = db.execute('SELECT * FROM users WHERE email = ?', (email,)).fetchone()
        
        if user:
            return jsonify({
                'success': True,
                'user_id': user['id'],
                'name': user['name'],
                'email': user['email']
            })
        else:
            return jsonify({'error': 'Пользователь не найден'}), 404
    
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    
    
@app.route('/api/products', methods=['GET'])
def get_products():
    """Получение всех товаров"""
    try:
        db = get_db()
        
        # Параметры фильтрации
        category = request.args.get('category')
        brand = request.args.get('brand')
        min_price = request.args.get('min_price')
        max_price = request.args.get('max_price')
        features = request.args.get('features')
        
        query = "SELECT * FROM products WHERE 1=1"
        params = []
        
        if category:
            query += " AND category = ?"
            params.append(category)
        
        if brand:
            query += " AND brand = ?"
            params.append(brand)
            
        if min_price:
            query += " AND price >= ?"
            params.append(float(min_price))
            
        if max_price:
            query += " AND price <= ?"
            params.append(float(max_price))
            
        if features:
            feature_list = features.split(',')
            for feature in feature_list:
                query += f" AND features LIKE ?"
                params.append(f'%{feature}%')
        
        products = db.execute(query, params).fetchall()
        
        # Преобразуем в словари
        result = []
        for product in products:
            product_dict = dict(product)
            # Преобразуем features из строки в список
            product_dict['features'] = product_dict['features'].split(',') if product_dict['features'] else []
            # Парсим details из JSON
            product_dict['details'] = json.loads(product_dict['details']) if product_dict['details'] else {}
            result.append(product_dict)
        
        return jsonify(result)
    
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/products/<int:product_id>', methods=['GET'])
def get_product(product_id):
    """Получение конкретного товара"""
    try:
        db = get_db()
        product = db.execute('SELECT * FROM products WHERE id = ?', (product_id,)).fetchone()
        
        if product:
            product_dict = dict(product)
            product_dict['features'] = product_dict['features'].split(',') if product_dict['features'] else []
            product_dict['details'] = json.loads(product_dict['details']) if product_dict['details'] else {}
            return jsonify(product_dict)
        else:
            return jsonify({'error': 'Product not found'}), 404
    
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/products/categories', methods=['GET'])
def get_categories():
    """Получение списка категорий"""
    try:
        db = get_db()
        categories = db.execute('SELECT DISTINCT category FROM products').fetchall()
        return jsonify([cat['category'] for cat in categories])
    
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/products/brands', methods=['GET'])
def get_brands():
    """Получение списка брендов"""
    try:
        db = get_db()
        brands = db.execute('SELECT DISTINCT brand FROM products').fetchall()
        return jsonify([brand['brand'] for brand in brands])
    
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# API endpoints для корзины
@app.route('/api/cart', methods=['GET'])
def get_cart():
    """Получение корзины пользователя"""
    try:
        user_id = request.args.get('user_id', 1)  # По умолчанию пользователь 1
        db = get_db()
        
        cart_items = db.execute('''
            SELECT c.*, p.name, p.price, p.image, p.brand 
            FROM cart c 
            JOIN products p ON c.product_id = p.id 
            WHERE c.user_id = ?
        ''', (user_id,)).fetchall()
        
        return jsonify([dict(item) for item in cart_items])
    
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/cart', methods=['POST'])
def add_to_cart():
    """Добавление товара в корзину"""
    try:
        data = request.json
        user_id = data.get('user_id', 1)
        product_id = data.get('product_id')
        quantity = data.get('quantity', 1)
        
        db = get_db()
        
        # Проверяем, есть ли уже товар в корзине
        existing_item = db.execute(
            'SELECT * FROM cart WHERE user_id = ? AND product_id = ?', 
            (user_id, product_id)
        ).fetchone()
        
        if existing_item:
            # Обновляем количество
            db.execute(
                'UPDATE cart SET quantity = quantity + ? WHERE user_id = ? AND product_id = ?',
                (quantity, user_id, product_id)
            )
        else:
            # Добавляем новый товар
            db.execute(
                'INSERT INTO cart (user_id, product_id, quantity) VALUES (?, ?, ?)',
                (user_id, product_id, quantity)
            )
        
        db.commit()
        return jsonify({'success': True})
    
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/cart/<int:product_id>', methods=['DELETE'])
def remove_from_cart(product_id):
    """Удаление товара из корзины"""
    try:
        user_id = request.args.get('user_id', 1)
        db = get_db()
        
        db.execute(
            'DELETE FROM cart WHERE user_id = ? AND product_id = ?',
            (user_id, product_id)
        )
        db.commit()
        
        return jsonify({'success': True})
    
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/cart/clear', methods=['DELETE'])
def clear_cart():
    """Очистка корзины"""
    try:
        user_id = request.args.get('user_id', 1)
        db = get_db()
        
        db.execute('DELETE FROM cart WHERE user_id = ?', (user_id,))
        db.commit()
        
        return jsonify({'success': True})
    
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# API endpoints для заказов
@app.route('/api/orders', methods=['GET'])
def get_orders():
    """Получение заказов пользователя"""
    try:
        user_id = request.args.get('user_id', 1)
        db = get_db()
        
        orders = db.execute(
            'SELECT * FROM orders WHERE user_id = ? ORDER BY created_at DESC',
            (user_id,)
        ).fetchall()
        
        # Парсим items из JSON
        result = []
        for order in orders:
            order_dict = dict(order)
            order_dict['items'] = json.loads(order_dict['items']) if order_dict['items'] else []
            result.append(order_dict)
        
        return jsonify(result)
    
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/orders', methods=['POST'])
def create_order():
    """Создание нового заказа"""
    try:
        data = request.json
        user_id = data.get('user_id', 1)
        
        db = get_db()
        
        # Получаем корзину пользователя
        cart_items = db.execute('''
            SELECT c.product_id, c.quantity, p.name, p.price, p.image
            FROM cart c 
            JOIN products p ON c.product_id = p.id 
            WHERE c.user_id = ?
        ''', (user_id,)).fetchall()
        
        if not cart_items:
            return jsonify({'error': 'Cart is empty'}), 400
        
        # Формируем items для заказа
        items = []
        total_amount = 0
        
        for item in cart_items:
            item_total = item['price'] * item['quantity']
            total_amount += item_total
            items.append({
                'product_id': item['product_id'],
                'name': item['name'],
                'price': item['price'],
                'quantity': item['quantity'],
                'image': item['image'],
                'total': item_total
            })
        
        # Создаем заказ
        order_data = {
            'user_id': user_id,
            'items': json.dumps(items, ensure_ascii=False),
            'total_amount': total_amount,
            'status': 'processing',
            'customer_name': data.get('customer_name'),
            'customer_email': data.get('customer_email'),
            'customer_phone': data.get('customer_phone'),
            'delivery_address': json.dumps(data.get('delivery_address', {}), ensure_ascii=False),
            'payment_method': data.get('payment_method'),
            'created_at': datetime.now().isoformat()
        }
        
        db.execute('''
            INSERT INTO orders 
            (user_id, items, total_amount, status, customer_name, customer_email, customer_phone, delivery_address, payment_method, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', tuple(order_data.values()))
        
        # Очищаем корзину
        db.execute('DELETE FROM cart WHERE user_id = ?', (user_id,))
        
        db.commit()
        
        return jsonify({'success': True, 'order_id': db.execute('SELECT last_insert_rowid()').fetchone()[0]})
    
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# API endpoints для избранного
@app.route('/api/wishlist', methods=['GET'])
def get_wishlist():
    """Получение избранного пользователя"""
    try:
        user_id = request.args.get('user_id', 1)
        db = get_db()
        
        wishlist_items = db.execute('''
            SELECT w.*, p.name, p.price, p.image, p.brand, p.rating
            FROM wishlist w 
            JOIN products p ON w.product_id = p.id 
            WHERE w.user_id = ?
        ''', (user_id,)).fetchall()
        
        return jsonify([dict(item) for item in wishlist_items])
    
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/wishlist', methods=['POST'])
def add_to_wishlist():
    """Добавление товара в избранное"""
    try:
        data = request.json
        user_id = data.get('user_id', 1)
        product_id = data.get('product_id')
        
        db = get_db()
        
        # Проверяем, есть ли уже товар в избранном
        existing_item = db.execute(
            'SELECT * FROM wishlist WHERE user_id = ? AND product_id = ?', 
            (user_id, product_id)
        ).fetchone()
        
        if not existing_item:
            db.execute(
                'INSERT INTO wishlist (user_id, product_id) VALUES (?, ?)',
                (user_id, product_id)
            )
            db.commit()
        
        return jsonify({'success': True})
    
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/wishlist/<int:product_id>', methods=['DELETE'])
def remove_from_wishlist(product_id):
    """Удаление товара из избранного"""
    try:
        user_id = request.args.get('user_id', 1)
        db = get_db()
        
        db.execute(
            'DELETE FROM wishlist WHERE user_id = ? AND product_id = ?',
            (user_id, product_id)
        )
        db.commit()
        
        return jsonify({'success': True})
    
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# API endpoints для блога
@app.route('/api/blog/posts', methods=['GET'])
def get_blog_posts():
    """Получение постов блога"""
    try:
        db = get_db()
        posts = db.execute('SELECT * FROM blog_posts ORDER BY date DESC').fetchall()
        return jsonify([dict(post) for post in posts])
    
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/blog/posts/<int:post_id>', methods=['GET'])
def get_blog_post(post_id):
    """Получение конкретного поста блога"""
    try:
        db = get_db()
        post = db.execute('SELECT * FROM blog_posts WHERE id = ?', (post_id,)).fetchone()
        
        if post:
            return jsonify(dict(post))
        else:
            return jsonify({'error': 'Post not found'}), 404
    
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# API endpoints для пользователей
@app.route('/api/users/profile', methods=['GET'])
def get_user_profile():
    """Получение профиля пользователя"""
    try:
        user_id = request.args.get('user_id', 1)
        db = get_db()
        
        profile = db.execute('SELECT * FROM users WHERE id = ?', (user_id,)).fetchone()
        
        if profile:
            return jsonify(dict(profile))
        else:
            # Создаем профиль по умолчанию
            default_profile = {
                'id': user_id,
                'name': 'Иван Иванов',
                'email': 'ivan@example.com',
                'phone': '+7 999 123-45-67',
                'bonuses': 150
            }
            return jsonify(default_profile)
    
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/users/profile', methods=['POST'])
def update_user_profile():
    """Обновление профиля пользователя"""
    try:
        data = request.json
        user_id = data.get('user_id', 1)
        
        db = get_db()
        
        # Проверяем, существует ли пользователь
        existing_user = db.execute('SELECT * FROM users WHERE id = ?', (user_id,)).fetchone()
        
        if existing_user:
            # Обновляем существующего пользователя
            db.execute('''
                UPDATE users SET name = ?, email = ?, phone = ?, bonuses = ? 
                WHERE id = ?
            ''', (data.get('name'), data.get('email'), data.get('phone'), data.get('bonuses', 0), user_id))
        else:
            # Создаем нового пользователя
            db.execute('''
                INSERT INTO users (id, name, email, phone, bonuses) 
                VALUES (?, ?, ?, ?, ?)
            ''', (user_id, data.get('name'), data.get('email'), data.get('phone'), data.get('bonuses', 0)))
        
        db.commit()
        return jsonify({'success': True})
    
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# Дополнительные API endpoints
@app.route('/api/newsletter/subscribe', methods=['POST'])
def subscribe_newsletter():
    """Подписка на рассылку"""
    try:
        data = request.json
        email = data.get('email')
        
        if not email:
            return jsonify({'error': 'Email is required'}), 400
        
        db = get_db()
        
        # Проверяем, есть ли уже email
        existing = db.execute('SELECT * FROM newsletter WHERE email = ?', (email,)).fetchone()
        
        if not existing:
            db.execute('INSERT INTO newsletter (email) VALUES (?)', (email,))
            db.commit()
        
        return jsonify({'success': True})
    
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/promo/validate', methods=['POST'])
def validate_promo():
    """Валидация промокода"""
    try:
        data = request.json
        promo_code = data.get('promo_code')
        
        valid_promos = {
            'WELCOME20': {'discount': 0.2, 'min_amount': 0},
            'ECO10': {'discount': 0.1, 'min_amount': 0},
            'NEWYEAR15': {'discount': 0.15, 'min_amount': 1000}
        }
        
        if promo_code in valid_promos:
            return jsonify({'valid': True, 'discount': valid_promos[promo_code]['discount']})
        else:
            return jsonify({'valid': False, 'error': 'Invalid promo code'})
    
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# Статические файлы
@app.route('/')
def serve_frontend():
    return send_from_directory('.', 'site.html')

@app.route('/site.css')
def serve_css():
    return send_from_directory('.', 'site.css')

@app.route('/site.js')
def serve_js():
    return send_from_directory('.', 'site.js')

if __name__ == '__main__':
    # Создаем базу данных при первом запуске
    if not os.path.exists(DATABASE):
        init_db()
    
    app.run(debug=DEBUG, port=5001)