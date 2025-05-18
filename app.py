"""
XRP Ledger Block Visualizer
This app connects to the XRP Ledger and visualizes blocks as animated characters.
"""

import json
import os
import logging
from logging.handlers import RotatingFileHandler
from datetime import datetime
from threading import Thread
import time
from collections import defaultdict
from decimal import Decimal

from flask import Flask, render_template
from flask_socketio import SocketIO

from xrpl.clients import WebsocketClient
from xrpl.models import Subscribe, StreamParameter
from xrpl.models.requests import Ledger

# Import functions from tx_parser
from tx_parser import (
    parse_transaction,
    analyze_block_transactions,
    get_transaction_type,
    get_amount_info,
    format_tx_info,
    format_block_stats
)

# Configure logging
log_dir = 'logs'
if not os.path.exists(log_dir):
    os.makedirs(log_dir)

# Create a logger
logger = logging.getLogger('xrp_visualizer')
logger.setLevel(logging.DEBUG)

# Configure console handler
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.INFO)
console_format = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
console_handler.setFormatter(console_format)

# Configure file handler with rotation
file_handler = RotatingFileHandler(
    os.path.join(log_dir, 'xrp_visualizer.log'),
    maxBytes=5*1024*1024,  # 5MB per file
    backupCount=5  # Keep 5 backup files
)
file_handler.setLevel(logging.DEBUG)
file_format = logging.Formatter('%(asctime)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s')
file_handler.setFormatter(file_format)

# Add handlers to logger
logger.addHandler(console_handler)
logger.addHandler(file_handler)

# Initialize Flask
app = Flask(__name__)
app.config['SECRET_KEY'] = 'xrp_ledger_visualizer'
socketio = SocketIO(app, cors_allowed_origins="*")
logger.info("Flask application initialized")

# Global variables
client = None
xrpl_thread = None
running = False

@app.route('/')
def index():
    """Render the main page."""
    return render_template('index.html')

def format_ledger_info(ledger_info):
    """Format ledger information in a human-readable format."""
    if not ledger_info or "type" not in ledger_info:
        return None
    
    if ledger_info["type"] != "ledgerClosed":
        return None
    
    timestamp = datetime.fromtimestamp(ledger_info.get("ledger_time", 0))
    formatted_time = timestamp.strftime("%Y-%m-%d %H:%M:%S")
    
    return {
        "ledger_hash": ledger_info.get('ledger_hash', 'N/A'),
        "ledger_index": ledger_info.get('ledger_index', 'N/A'),
        "formatted_time": formatted_time,
        "txn_count": ledger_info.get('txn_count', 0),
        "reserve_base": ledger_info.get('reserve_base', 'N/A'),
        "reserve_inc": ledger_info.get('reserve_inc', 'N/A'),
        "fee_base": ledger_info.get('fee_base', 'N/A')
    }

def xrpl_listener():
    """Listen to the XRP Ledger for new blocks."""
    global client, running
    
    # XRP Ledger mainnet websocket URL
    mainnet_url = "wss://xrplcluster.com/"
    
    logger.info("Connecting to XRP Ledger mainnet...")
    
    try:
        with WebsocketClient(mainnet_url) as client:
            logger.info(f"Connected to {mainnet_url}")
            logger.info("Subscribing to ledger stream...")
            
            # Subscribe to ledger stream
            subscribe_request = Subscribe(streams=[StreamParameter.LEDGER])
            client.send(subscribe_request)
            
            logger.info("Waiting for ledger closures.")
            
            for message in client:
                if not running:
                    logger.debug("Stopping XRPL listener as running flag is False")
                    break
                    
                # Check if this is a ledger closed message
                if message and isinstance(message, dict) and message.get("type") == "ledgerClosed":
                    # Format the ledger information
                    ledger_info = format_ledger_info(message)
                    if ledger_info:
                        ledger_hash = message.get('ledger_hash')
                        ledger_index = ledger_info['ledger_index']
                        txn_count = ledger_info['txn_count']
                        logger.info(f"New ledger: #{ledger_index} with {txn_count} transactions")
                        
                        # Only fetch detailed transactions if there are any
                        tx_details = {}
                        if txn_count > 0:
                            try:
                                # Fetch all transactions for this ledger
                                logger.debug(f"Fetching transactions for ledger #{ledger_index}")
                                transactions = get_ledger_transactions(client, ledger_hash)
                                
                                # Analyze the transactions
                                if transactions:
                                    logger.debug(f"Analyzing {len(transactions)} transactions from ledger #{ledger_index}")
                                    
                                    # Debug: Print structure of the first transaction to understand format
                                    if len(transactions) > 0:
                                        first_tx = transactions[0]
                                        logger.debug(f"First transaction type: {type(first_tx)}")
                                        logger.debug(f"First transaction keys: {list(first_tx.keys()) if isinstance(first_tx, dict) else 'Not a dict'}")
                                        if isinstance(first_tx, dict):
                                            # Check if TransactionType exists directly
                                            if 'TransactionType' in first_tx:
                                                logger.debug(f"Transaction type from key: {first_tx['TransactionType']}")
                                            # Try the get_transaction_type function
                                            tx_type = get_transaction_type(first_tx)
                                            logger.debug(f"Transaction type from function: {tx_type}")
                                            # Check common nested locations
                                            for location in ['tx', 'transaction', 'meta']:
                                                if location in first_tx and isinstance(first_tx[location], dict):
                                                    logger.debug(f"Contents in '{location}': {list(first_tx[location].keys())}")
                                        
                                        # Print a sample of the transaction to inspect
                                        tx_sample = json.dumps(first_tx)[:500]
                                        logger.debug(f"Transaction sample: {tx_sample}...")
                                    
                                    # Use the analyze_block_transactions function from tx_parser
                                    tx_stats = analyze_block_transactions(transactions)
                                    
                                    # Log detailed parsing information
                                    logger.info(f"Transaction parsing complete for ledger #{ledger_index}")
                                    logger.debug(f"Transaction types found: {list(tx_stats['transaction_types'].keys())}")
                                    
                                    # Format transaction data for the frontend
                                    tx_details = {
                                        "transaction_types": tx_stats["transaction_types"],
                                        "currencies": tx_stats.get("currencies", {}),
                                        "largest_payment": float(tx_stats.get("largest_payment", 0)),
                                        "total_xrp_transferred": float(tx_stats.get("total_xrp_transferred", 0)),
                                        "total_fees": float(tx_stats.get("total_fees", 0)),
                                        "significant_accounts": tx_stats.get("active_accounts", [])[:5] if "active_accounts" in tx_stats else [],
                                        "detailed_transactions": tx_stats.get("sample_transactions", [])[:10] if "sample_transactions" in tx_stats else [],
                                        "special_wallet_received_xrp": tx_stats.get("special_wallet_received_xrp", False),
                                        "special_wallet_received_exact_amount": tx_stats.get("special_wallet_received_exact_amount", False)
                                    }
                                    
                                    # Log if special wallet received XRP
                                    if tx_stats.get("special_wallet_received_xrp", False):
                                        logger.info(f"SPECIAL WALLET RECEIVED XRP IN LEDGER #{ledger_index}!")
                                        
                                    # Log if special wallet received exactly 0.00101 XRP
                                    if tx_stats.get("special_wallet_received_exact_amount", False):
                                        logger.info(f"SPECIAL WALLET RECEIVED EXACTLY 0.00101 XRP IN LEDGER #{ledger_index}!")
                                    
                                    # Log summary of analyzed data
                                    logger.info(f"Analyzed {len(transactions)} transactions in ledger #{ledger_index}: {len(tx_stats.get('transaction_types', {}))} types, {tx_stats.get('total_xrp_transferred', 0):.2f} XRP transferred")
                                    if tx_stats.get("largest_payment", 0) > 0:
                                        logger.info(f"Largest payment in ledger: {tx_stats.get('largest_payment', 0):.2f} XRP")
                                else:
                                    logger.warning(f"No transactions returned for ledger #{ledger_index} despite txn_count={txn_count}")
                            except Exception as tx_error:
                                logger.error(f"Error processing transactions for ledger #{ledger_index}: {tx_error}", exc_info=True)
                        
                        # Add transaction details to ledger info
                        ledger_info["tx_details"] = tx_details
                        
                        # Send to all connected clients
                        socketio.emit('new_block', ledger_info)
                        logger.debug(f"Emitted ledger #{ledger_index} data to connected clients")
                
    except Exception as e:
        logger.error(f"An error occurred in XRPL listener: {e}", exc_info=True)
    finally:
        logger.info("XRPL listener stopped")

@socketio.on('connect')
def handle_connect():
    """Handle client connection."""
    logger.info("Client connected")
    # Send current connection status to the newly connected client
    socketio.emit('connection_status', {'status': 'connected', 'server_time': datetime.now().isoformat()})

@socketio.on('disconnect')
def handle_disconnect():
    """Handle client disconnection."""
    logger.info("Client disconnected")
    
@socketio.on('heartbeat')
def handle_heartbeat(data):
    """Handle heartbeat from client to keep connection alive."""
    logger.debug(f"Received heartbeat from client, timestamp: {data.get('timestamp')}")
    # Send response heartbeat back to confirm server is also alive
    socketio.emit('heartbeat_response', {
        'server_time': datetime.now().isoformat(),
        'client_time': data.get('timestamp')
    })
    
@socketio.on('frontend_event')
def handle_frontend_event(data):
    """Handle events reported by the frontend."""
    event_type = data.get('type')
    event_data = data.get('data', {})
    
    logger.info(f"Frontend event received: {event_type}, data: {event_data}")
    
    # Special handling for wallet detection events
    if event_type == 'special_wallet_detection':
        detection_type = event_data.get('type')
        logger.info(f"Frontend detected special wallet payment: {detection_type}")

def start_xrpl_thread():
    """Start the XRPL listener thread."""
    global xrpl_thread, running
    
    if xrpl_thread is None or not xrpl_thread.is_alive():
        running = True
        xrpl_thread = Thread(target=xrpl_listener, name="XRPL_Listener_Thread")
        xrpl_thread.daemon = True
        xrpl_thread.start()
        logger.info("XRPL listener thread started")
    else:
        logger.info("XRPL listener thread is already running")

# Note: get_transaction_type function now imported from tx_parser.py


# Note: get_amount_info function now imported from tx_parser.py


def get_ledger_transactions(client, ledger_hash):
    """Fetch all transactions for a given ledger."""
    try:
        # First, check if there are transactions in this ledger
        request = Ledger(ledger_hash=ledger_hash, transactions=True, expand=True)
        logger.debug(f"Requesting ledger data for hash {ledger_hash[:10]}...")
        response = client.request(request)
        
        if response.is_successful():
            result = response.result
            if "ledger" in result and "transactions" in result["ledger"]:
                transactions = result["ledger"]["transactions"]
                
                # Check if transactions is a list
                if not isinstance(transactions, list):
                    logger.warning(f"Unexpected transactions format: {type(transactions)}")
                    return []
                
                logger.info(f"Found {len(transactions)} transactions in ledger with hash {ledger_hash[:10]}...")
                return transactions
            else:
                logger.warning("No transactions field in ledger result")
        else:
            logger.error(f"Failed to fetch ledger: {response.result}")
        
        return []
    except Exception as e:
        logger.error(f"Error fetching transactions: {e}", exc_info=True)
        return []


# Note: analyze_transactions function now imported from tx_parser as analyze_block_transactions


def stop_xrpl_thread():
    """Stop the XRPL listener thread."""
    global running, xrpl_thread
    running = False
    logger.info("XRPL listener thread stop requested")
    
    if xrpl_thread and xrpl_thread.is_alive():
        logger.debug(f"Waiting for XRPL listener thread to terminate")
        # Don't join the thread since it's daemon and will terminate when the main program exits

if __name__ == '__main__':
    try:
        logger.info("Starting XRPL listener thread")
        start_xrpl_thread()
        logger.info("Starting SocketIO server")
        socketio.run(app, debug=True, host='0.0.0.0', port=8000, allow_unsafe_werkzeug=True)
    except Exception as e:
        logger.error(f"Error starting XRPL listener or SocketIO server: {e}", exc_info=True)
    finally:
        logger.info("Stopping XRPL listener thread")
        stop_xrpl_thread()
