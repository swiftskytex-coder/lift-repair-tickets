#!/usr/bin/env python3
"""
MCP STDIO Server for Lift Repair Tickets
"""

import sys
import os
import json

sys.path.insert(0, '/Users/swiftpanaev/KIRO/test4')
os.chdir('/Users/swiftpanaev/KIRO/test4')

from ticket_db import db

def create_response(request_id, result):
    return json.dumps({
        "jsonrpc": "2.0",
        "id": request_id,
        "result": result
    })

def create_error(request_id, code, message):
    return json.dumps({
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {
            "code": code,
            "message": message
        }
    })

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
        "description": "Mark a ticket as completed",
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
        
        return {"error": f"Unknown tool: {name}"}
    except Exception as e:
        return {"error": str(e)}

initialized = False

for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    
    try:
        request = json.loads(line)
    except json.JSONDecodeError:
        continue
    
    request_id = request.get("id")
    method = request.get("method")
    
    if method == "initialize":
        initialized = True
        response = {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {}},
            "serverInfo": {
                "name": "lift-repair-tickets",
                "version": "1.0.0"
            },
            "tools": tools
        }
        sys.stdout.write(create_response(request_id, response) + "\n")
    
    elif method == "tools/list":
        sys.stdout.write(create_response(request_id, {"tools": tools}) + "\n")
    
    elif method == "tools/call":
        params = request.get("params", {})
        tool_name = params.get("name")
        arguments = params.get("arguments", {})
        result = call_tool(tool_name, arguments)
        sys.stdout.write(create_response(request_id, {"content": [{"type": "text", "text": json.dumps(result)}]}) + "\n")
    
    else:
        sys.stdout.write(create_error(request_id, -32601, f"Unknown method: {method}") + "\n")
    
    sys.stdout.flush()