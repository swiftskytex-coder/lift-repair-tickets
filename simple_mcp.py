"""
Simple MCP-like API Server for Lift Repair Tickets
 Веб-сервер для доступа к функциям системы через AI агентов
"""

import sys
sys.path.insert(0, '/Users/swiftpanaev/KIRO/test4')

import json
import os
import uuid
from datetime import datetime
from flask import Flask, request, jsonify, send_from_directory
from werkzeug.utils import secure_filename
from ticket_db import db

app = Flask(__name__)
# app.config['UPLOAD_FOLDER'] = '/app/uploads/reports'
# For Docker: use /app/uploads, for local: use local path
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max
app.config['UPLOAD_FOLDER'] = '/app/uploads/reports'

# Make uploads folder serve static files
import os
uploads_path = os.path.join(os.path.dirname(__file__), 'uploads')
if os.path.exists(uploads_path):
    app.static_folder = uploads_path
    app.static_url_path = '/uploads'

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

tools = [
    {
        "name": "get_mechanic_tickets",
        "description": "Get tickets assigned to a mechanic by phone number",
        "inputSchema": {
            "type": "object",
            "properties": {
                "phone": {"type": "string", "description": "Mechanic phone number"}
            },
            "required": ["phone"]
        }
    },
    {
        "name": "get_ticket_info",
        "description": "Get information about a specific ticket",
        "inputSchema": {
            "type": "object",
            "properties": {
                "ticket_id": {"type": "integer", "description": "Ticket ID"}
            },
            "required": ["ticket_id"]
        }
    },
    {
        "name": "accept_ticket",
        "description": "Accept a ticket for work",
        "inputSchema": {
            "type": "object",
            "properties": {
                "ticket_id": {"type": "integer", "description": "Ticket ID to accept"},
                "phone": {"type": "string", "description": "Mechanic phone number"}
            },
            "required": ["ticket_id", "phone"]
        }
    },
    {
        "name": "complete_ticket",
        "description": "Mark a ticket as completed with optional work description",
        "inputSchema": {
            "type": "object",
            "properties": {
                "ticket_id": {"type": "integer", "description": "Ticket ID"},
                "phone": {"type": "string", "description": "Mechanic phone number"},
                "work_done": {"type": "string", "description": "Work description"}
            },
            "required": ["ticket_id", "phone"]
        }
    },
    {
        "name": "upload_ticket_photo",
        "description": "Upload a photo to a ticket for repair report",
        "inputSchema": {
            "type": "object",
            "properties": {
                "ticket_id": {"type": "integer", "description": "Ticket ID"},
                "phone": {"type": "string", "description": "Mechanic phone number"},
                "photo_url": {"type": "string", "description": "URL of the photo to upload (from multipart form or base64)"}
            },
            "required": ["ticket_id", "phone"]
        }
    },
    {
        "name": "get_ticket_photos",
        "description": "Get photos attached to a ticket",
        "inputSchema": {
            "type": "object",
            "properties": {
                "ticket_id": {"type": "integer", "description": "Ticket ID"}
            },
            "required": ["ticket_id"]
        }
    },
    {
        "name": "get_mechanic_info",
        "description": "Get mechanic information",
        "inputSchema": {
            "type": "object",
            "properties": {
                "phone": {"type": "string", "description": "Mechanic phone number"}
            },
            "required": ["phone"]
        }
    },
    {
        "name": "get_mechanic_elevators",
        "description": "Get elevators assigned to a mechanic",
        "inputSchema": {
            "type": "object",
            "properties": {
                "phone": {"type": "string", "description": "Mechanic phone number"}
            },
            "required": ["phone"]
        }
    },
    {
        "name": "search_tickets",
        "description": "Search tickets by filters",
        "inputSchema": {
            "type": "object",
            "properties": {
                "status": {"type": "string", "description": "Filter by status"},
                "priority": {"type": "string", "description": "Filter by priority"},
                "address": {"type": "string", "description": "Filter by address"},
                "limit": {"type": "integer", "description": "Max results"}
            }
        }
    },
    {
        "name": "get_statistics",
        "description": "Get ticket statistics",
        "inputSchema": {"type": "object", "properties": {}}
    }
]

def call_tool(name, args):
    try:
        if name == "get_mechanic_tickets":
            mechanic = db.get_mechanic_by_phone(args['phone'])
            if not mechanic:
                return {"error": "Механик не найден"}
            tickets = db.get_all_mechanic_tickets(mechanic['id'])
            return {"mechanic": mechanic['name'], "tickets": tickets}
        
        elif name == "accept_ticket":
            mechanic = db.get_mechanic_by_phone(args['phone'])
            db.update_ticket_status(args['ticket_id'], 'в работе', f'max_bot (принял {mechanic["name"]})')
            db.assign_ticket(args['ticket_id'], mechanic['id'])
            return {"success": True, "message": "Заявка принята"}
        
        elif name == "complete_ticket":
            mechanic = db.get_mechanic_by_phone(args['phone'])
            db.update_ticket_status(args['ticket_id'], 'выполнена', f'max_bot (завершил {mechanic["name"]})')
            if args.get('work_done'):
                db.add_comment(args['ticket_id'], 'mechanic', f'📝 {args["work_done"]}')
            return {"success": True, "message": "Заявка завершена"}
        
        elif name == "get_mechanic_info":
            mechanic = db.get_mechanic_by_phone(args['phone'])
            if not mechanic:
                return {"error": "Механик не найден"}
            return mechanic
        
        elif name == "get_mechanic_elevators":
            mechanic = db.get_mechanic_by_phone(args['phone'])
            if not mechanic:
                return {"error": "Механик не найден"}
            elevators = db.get_mechanic_elevators(mechanic['id'])
            return {"elevators": elevators}
        
        elif name == "get_ticket_info":
            ticket = db.get_ticket(args['ticket_id'])
            if not ticket:
                return {"error": "Заявка не найдена"}
            return ticket
        
        elif name == "search_tickets":
            filters = {}
            if args.get('status'): filters['status'] = args['status']
            if args.get('priority'): filters['priority'] = args['priority']
            if args.get('address'): filters['address'] = args['address']
            tickets = db.search_tickets(filters=filters if filters else None, limit=args.get('limit', 50))
            return {"tickets": tickets}
        
        elif name == "get_statistics":
            return db.get_statistics()
        
        elif name == "upload_ticket_photo":
            ticket_id = args.get('ticket_id')
            phone = args.get('phone')
            photo_url = args.get('photo_url')
            
            mechanic = db.get_mechanic_by_phone(phone)
            if not mechanic:
                return {"error": "Механик не найден"}
            
            ticket = db.get_ticket(ticket_id)
            if not ticket:
                return {"error": "Заявка не найдена"}
            
            if photo_url:
                db.add_comment(ticket_id, 'mechanic', f'[ФОТО] {photo_url}')
                return {"success": True, "message": "Фото добавлено", "photo_url": photo_url}
            
            return {"error": "photo_url required"}
        
        elif name == "get_ticket_photos":
            ticket_id = args.get('ticket_id')
            ticket = db.get_ticket(ticket_id)
            if not ticket:
                return {"error": "Заявка не найдена"}
            
            conn = db.get_connection()
            cursor = conn.execute(
                "SELECT text FROM ticket_comments WHERE ticket_id = ? AND text LIKE '[ФОТО] %'",
                (ticket_id,)
            )
            photos = [row[0].replace('[ФОТО] ', '') for row in cursor.fetchall()]
            return {"ticket_id": ticket_id, "photos": photos}
        
        return {"error": f"Unknown tool: {name}"}
    except Exception as e:
        return {"error": str(e)}

@app.route('/mcp', methods=['GET', 'POST'])
def mcp_endpoint():
    """MCP protocol endpoint"""
    if request.method == 'GET':
        return jsonify({"tools": tools})
    
    data = request.get_json()
    method = data.get('method')
    request_id = data.get('id', 1)
    
    if method == 'tools/list':
        return jsonify({"tools": tools})
    
    elif method == 'tools/call':
        params = data.get('params', {})
        tool_name = params.get('name')
        arguments = params.get('arguments', {})
        result = call_tool(tool_name, arguments)
        return jsonify({
            "content": [{"type": "text", "text": json.dumps(result)}]
        })
    
    return jsonify({"error": f"Unknown method: {method}"})

@app.route('/mcp/tools', methods=['GET'])
def list_tools():
    return jsonify({"tools": tools})

@app.route('/mcp/call', methods=['POST'])
def call_tool_endpoint():
    data = request.get_json()
    tool = data.get('tool')
    params = data.get('params', {})
    
    try:
        if tool == "get_mechanic_tickets":
            mechanic = db.get_mechanic_by_phone(params['phone'])
            if not mechanic:
                return jsonify({"error": "Механик не найден"})
            tickets = db.get_all_mechanic_tickets(mechanic['id'])
            return jsonify({
                "mechanic": mechanic['name'],
                "tickets": [{"id": t['id'], "ticket_number": t.get('ticket_number'), 
                            "address": t['address'], "status": t['status'], 
                            "priority": t['priority']} for t in tickets]
            })
        
        elif tool == "accept_ticket":
            mechanic = db.get_mechanic_by_phone(params['phone'])
            db.update_ticket_status(params['ticket_id'], 'в работе', f'max_bot (принял {mechanic["name"]})')
            db.assign_ticket(params['ticket_id'], mechanic['id'])
            return jsonify({"success": True, "message": "Заявка принята"})
        
        elif tool == "complete_ticket":
            mechanic = db.get_mechanic_by_phone(params['phone'])
            db.update_ticket_status(params['ticket_id'], 'выполнена', f'max_bot (завершил {mechanic["name"]})')
            if params.get('work_done'):
                db.add_comment(params['ticket_id'], 'mechanic', f'📝 {params["work_done"]}')
            return jsonify({"success": True, "message": "Заявка завершена"})
        
        elif tool == "get_mechanic_info":
            mechanic = db.get_mechanic_by_phone(params['phone'])
            if not mechanic:
                return jsonify({"error": "Механик не найден"})
            return jsonify({"name": mechanic['name'], "phone": mechanic['phone'], 
                          "status": mechanic['status'], "id": mechanic['id']})
        
        elif tool == "get_mechanic_elevators":
            mechanic = db.get_mechanic_by_phone(params['phone'])
            if not mechanic:
                return jsonify({"error": "Механик не найден"})
            elevators = db.get_mechanic_elevators(mechanic['id'])
            return jsonify({"elevators": [{"elevator_id": e['elevator_id'], "address": e['address']} for e in elevators]})
        
        elif tool == "get_ticket_info":
            ticket = db.get_ticket(params['ticket_id'])
            if not ticket:
                return jsonify({"error": "Заявка не найдена"})
            return jsonify(ticket)
        
        elif tool == "search_tickets":
            filters = {}
            if params.get('status'): filters['status'] = params['status']
            if params.get('priority'): filters['priority'] = params['priority']
            if params.get('address'): filters['address'] = params['address']
            tickets = db.search_tickets(filters=filters if filters else None, limit=params.get('limit', 50))
            return jsonify({"tickets": tickets})
        
        elif tool == "get_statistics":
            return jsonify(db.get_statistics())
        
        elif tool == "upload_ticket_photo":
            ticket_id = params.get('ticket_id')
            phone = params.get('phone')
            photo_url = params.get('photo_url')
            
            mechanic = db.get_mechanic_by_phone(phone)
            if not mechanic:
                return jsonify({"error": "Механик не найден"}), 404
            
            ticket = db.get_ticket(ticket_id)
            if not ticket:
                return jsonify({"error": "Заявка не найдена"}), 404
            
            if photo_url:
                db.add_comment(ticket_id, 'mechanic', f'[ФОТО] {photo_url}')
                return jsonify({"success": True, "message": "Фото добавлено", "photo_url": photo_url})
            
            return jsonify({"error": "photo_url required"}), 400
        
        elif tool == "get_ticket_photos":
            ticket_id = params.get('ticket_id')
            ticket = db.get_ticket(ticket_id)
            if not ticket:
                return jsonify({"error": "Заявка не найдена"}), 404
            
            conn = db.get_connection()
            cursor = conn.execute(
                "SELECT text FROM ticket_comments WHERE ticket_id = ? AND text LIKE '[ФОТО] %'",
                (ticket_id,)
            )
            photos = [row[0].replace('[ФОТО] ', '') for row in cursor.fetchall()]
            return jsonify({"ticket_id": ticket_id, "photos": photos})
        
        else:
            return jsonify({"error": f"Unknown tool: {tool}"})
    
    except Exception as e:
        return jsonify({"error": str(e)})

@app.route('/mcp/upload', methods=['POST'])
def upload_photo():
    """Загрузка фото через multipart/form-data"""
    if 'photo' not in request.files:
        return jsonify({'error': 'No photo provided'}), 400
    
    photo = request.files['photo']
    ticket_id = request.form.get('ticket_id')
    phone = request.form.get('phone')
    
    if not ticket_id or not phone:
        return jsonify({'error': 'ticket_id and phone required'}), 400
    
    if photo.filename == '':
        return jsonify({'error': 'No selected file'}), 400
    
    if photo and allowed_file(photo.filename):
        os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
        
        ext = photo.filename.rsplit('.', 1)[1].lower() if '.' in photo.filename else 'jpg'
        filename = f"{uuid.uuid4()}.{ext}"
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        photo.save(filepath)
        
        photo_url = f"/uploads/reports/{filename}"
        
        mechanic = db.get_mechanic_by_phone(phone)
        if not mechanic:
            return jsonify({'error': 'Механик не найден'}), 404
        
        db.add_comment(int(ticket_id), 'mechanic', f'[ФОТО] {photo_url}')
        
        return jsonify({
            'success': True, 
            'message': 'Фото загружено',
            'photo_url': photo_url,
            'ticket_id': int(ticket_id)
        })
    
    return jsonify({'error': 'Invalid file type'}), 400

@app.route('/uploads/reports/<filename>')
def serve_report_photo(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

if __name__ == "__main__":
    print("🚀 MCP API Server: http://localhost:8082/mcp")
    app.run(host='0.0.0.0', port=8082, debug=False)