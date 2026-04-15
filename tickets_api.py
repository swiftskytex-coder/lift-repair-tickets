"""
Tickets API Server on port 8084
 Simple REST API for ticket data
"""

import sys
sys.path.insert(0, '/Users/swiftpanaev/KIRO/test4')

from flask import Flask, jsonify, request
from ticket_db import db

app = Flask(__name__)

@app.route('/api/tickets', methods=['GET'])
def get_tickets():
    """Get all tickets with optional filters"""
    status = request.args.get('status')
    priority = request.args.get('priority')
    limit = request.args.get('limit', 50, type=int)
    
    filters = {}
    if status:
        filters['status'] = status
    if priority:
        filters['priority'] = priority
    
    tickets = db.search_tickets(filters=filters if filters else None, limit=limit)
    return jsonify({"tickets": tickets, "count": len(tickets)})

@app.route('/api/tickets/<int:ticket_id>', methods=['GET'])
def get_ticket(ticket_id):
    """Get specific ticket"""
    ticket = db.get_ticket(ticket_id)
    if not ticket:
        return jsonify({"error": "Заявка не найдена"}), 404
    return jsonify(ticket)

@app.route('/api/mechanics', methods=['GET'])
def get_mechanics():
    """Get all mechanics"""
    mechanics = db.get_all_mechanics()
    return jsonify({"mechanics": mechanics, "count": len(mechanics)})

@app.route('/api/mechanics/<int:mechanic_id>/tickets', methods=['GET'])
def get_mechanic_tickets(mechanic_id):
    """Get tickets for a mechanic"""
    tickets = db.get_all_mechanic_tickets(mechanic_id)
    return jsonify({"tickets": tickets, "count": len(tickets)})

@app.route('/api/elevators', methods=['GET'])
def get_elevators():
    """Get all elevators"""
    elevators = db.get_all_elevators()
    return jsonify({"elevators": elevators, "count": len(elevators)})

@app.route('/api/statistics', methods=['GET'])
def get_stats():
    """Get statistics"""
    return jsonify(db.get_statistics())

@app.route('/api/health', methods=['GET'])
def health():
    return jsonify({"status": "healthy"})

if __name__ == "__main__":
    print("📋 Tickets API: http://localhost:8084")
    app.run(host='0.0.0.0', port=8084, debug=False)