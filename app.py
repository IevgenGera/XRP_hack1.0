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

from flask import Flask, render_template, copy_current_request_context
from flask_socketio import SocketIO, emit

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

# Initialize Flask app and SocketIO
app = Flask(__name__)
app.config['SECRET_KEY'] = 'xrp_ledger_visualizer'  # Change for production

# Enhanced SocketIO setup for Railway deployment
socketio = SocketIO(app, 
                   cors_allowed_origins="*",
                   logger=True, 
                   engineio_logger=True,
                   ping_timeout=120,  # Extended ping timeout
                   ping_interval=25,
                   async_mode='eventlet',  # Use eventlet for production
                   manage_session=False)  # Disable Flask session management for better performance
logger.info("Flask application initialized with optimized Socket.IO settings")

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
    """Listen to the XRP Ledger for new blocks with robust error handling."""
    global client, running
    
    # XRP Ledger mainnet websocket URLs - primary and fallback options
    urls = [
        "wss://xrplcluster.com/",
        "wss://s1.ripple.com/",
        "wss://s2.ripple.com/"
    ]
    current_url_index = 0
    reconnect_delay = 5  # Start with 5 seconds delay
    max_reconnect_delay = 60  # Maximum delay of 60 seconds
    consecutive_errors = 0
    max_consecutive_errors = 3
    
    while running:
        current_url = urls[current_url_index]
        logger.info(f"Connecting to XRP Ledger: {current_url}")
        
        try:
            with WebsocketClient(current_url) as client:
                # Reset error counter and reconnect delay on successful connection
                consecutive_errors = 0
                reconnect_delay = 5
                
                logger.info(f"Connected successfully to {current_url}")
                logger.info("Subscribing to ledger stream...")
                
                # Subscribe to ledger stream
                subscribe_request = Subscribe(streams=[StreamParameter.LEDGER])
                client.send(subscribe_request)
                
                logger.info("Waiting for ledger closures...")
                
                # Notify clients about successful connection
                socketio.emit('xrpl_connection_status', {
                    'status': 'connected',
                    'url': current_url,
                    'timestamp': datetime.now().isoformat()
                })
                
                # Set up a last message timestamp to detect stalled connections
                last_message_time = time.time()
                heartbeat_interval = 30  # seconds
                
                for message in client:
                    if not running:
                        logger.debug("Stopping XRPL listener as running flag is False")
                        break
                    
                    # Update last message timestamp whenever we get any message
                    last_message_time = time.time()
                    
                    # Check for heartbeat/pong messages to ensure connection is alive
                    if message and isinstance(message, dict) and message.get("type") == "pong":
                        logger.debug("Received pong from XRPL server")
                        continue
                    
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
                                        
                                        # UPDATED APPROACH: Focus specifically on transactions to ra22VZUKQbznAAQooPYffPPXs4MUFwqVeH
                                        
                                        # Retrieve special wallet info - this should be correct from tx_parser.py now
                                        special_wallet_received = tx_stats.get("special_wallet_received_xrp", False)
                                        has_special_wallet_memo = tx_stats.get("has_special_wallet_memo", False)
                                        special_wallet_memos = tx_stats.get("special_wallet_memos", [])
                                        special_wallet_memo_tx_hash = tx_stats.get("special_wallet_memo_tx_hash", None)
                                        
                                        # Log detailed special wallet and memo status
                                        logger.info(f"🔎 MEMO CHECK: special_wallet_received={special_wallet_received}, "
                                                    f"has_special_wallet_memo={has_special_wallet_memo}, "
                                                    f"special_wallet_memos count={len(special_wallet_memos)}")
                                        
                                        # Debug memo contents
                                        if special_wallet_memos and len(special_wallet_memos) > 0:
                                            for i, memo in enumerate(special_wallet_memos):
                                                logger.info(f"📝 SPECIAL WALLET MEMO #{i+1}: {memo.get('memo_data', 'empty')} (tx: {memo.get('tx_hash', 'unknown')})")
                                        
                                        # Log all regular memos for comparison
                                        regular_memos = tx_stats.get("transaction_memos", [])
                                        if regular_memos and len(regular_memos) > 0:
                                            logger.info(f"📋 Found {len(regular_memos)} regular memos")
                                            for i, memo in enumerate(regular_memos[:3]):  # Log up to 3 for brevity
                                                logger.info(f"📋 REGULAR MEMO #{i+1}: {memo.get('memo_data', 'empty')} (tx: {memo.get('tx_hash', 'unknown')})")
                                        
                                        # If transaction has memos and was sent to the special wallet ra22VZUKQbznAAQooPYffPPXs4MUFwqVeH
                                        # Make sure we use ONLY those memos
                                        if special_wallet_received and special_wallet_memos and len(special_wallet_memos) > 0:
                                            logger.info(f"🏆🏆🏆 PRIORITY: Found a transaction to THE SPECIAL WALLET ra22VZUKQbznAAQooPYffPPXs4MUFwqVeH with memo")
                                            logger.info(f"💹 Special wallet transaction hash: {special_wallet_memo_tx_hash}")
                                            
                                            # Get the count of regular memos before clearing
                                            regular_memo_count = len(tx_stats.get("transaction_memos", []))
                                            
                                            # Completely clear regular transaction memos
                                            tx_stats["transaction_memos"] = []
                                            logger.info(f"🧹 Cleared {regular_memo_count} regular transaction memos")
                                            
                                            # Set the flag to ensure frontend recognizes the special wallet memo
                                            tx_stats["has_special_wallet_memo"] = True
                                            logger.info(f"🚩 Set has_special_wallet_memo flag to TRUE")
                                            
                                            # Debug the special wallet memo content in detail
                                            if special_wallet_memos[0]:
                                                memo = special_wallet_memos[0]
                                                logger.info(f"🔍 SPECIAL WALLET MEMO DETAILS:")
                                                logger.info(f"   - Content: '{memo.get('memo_data', '')}'")
                                                logger.info(f"   - Type: '{memo.get('memo_type', '')}'")
                                                logger.info(f"   - Format: '{memo.get('memo_format', '')}'") 
                                                logger.info(f"   - Transaction: {memo.get('tx_hash', 'unknown')}")
                                        
                                        # Extra logging of what memos will be sent
                                        logger.info(f"Final memo counts: special={len(special_wallet_memos)}, regular={len(tx_stats.get('transaction_memos', []))}")
                                        
                                        # Format transaction data for the frontend
                                        # Super explicit final memo selection logic - absolutely prioritize special wallet memos
                                        
                                        # Initialize empty memo containers
                                        final_transaction_memos = []
                                        final_special_wallet_memos = []
                                        
                                        # Always check for special wallet memos first - WITH EXTREME VERIFICATION
                                        if special_wallet_received:
                                            logger.info(f"✅ VERIFICATION: Special wallet received XRP")
                                            
                                            # Explicitly re-check memo existence
                                            special_wallet_memo_list = tx_stats.get("special_wallet_memos", [])
                                            if special_wallet_memo_list and len(special_wallet_memo_list) > 0:
                                                logger.info(f"✅ VERIFICATION: Found {len(special_wallet_memo_list)} special wallet memos")
                                                
                                                # ULTRA-VERIFY EACH MEMO
                                                verified_memos = []
                                                for i, memo in enumerate(special_wallet_memo_list):
                                                    memo_data = memo.get('memo_data', '')
                                                    tx_hash = memo.get('tx_hash', 'unknown')
                                                    
                                                    if isinstance(memo_data, str) and memo_data.strip():
                                                        logger.info(f"✅ VERIFIED memo #{i+1}: '{memo_data}' from tx {tx_hash}")
                                                        verified_memos.append(memo)
                                                    else:
                                                        logger.info(f"❌ INVALID memo #{i+1} from tx {tx_hash} - not adding to verified list")
                                                
                                                # Use only verified memos
                                                if verified_memos:
                                                    final_special_wallet_memos = verified_memos
                                                    logger.info(f"🏆 SPECIAL WALLET MEMO SELECTED: '{final_special_wallet_memos[0].get('memo_data')}' from tx {final_special_wallet_memos[0].get('tx_hash')}")
                                                    logger.info(f"💯 FINAL DECISION: Using ONLY special wallet memos ({len(final_special_wallet_memos)})")
                                                else:
                                                    logger.info(f"⚠️ All special wallet memos failed verification - not using any")
                                            else:
                                                logger.info(f"⚠️ Special wallet received XRP but no valid memos were found")
                                        
                                        # Only use regular transaction memos if there are NO special wallet memos
                                        if not final_special_wallet_memos and tx_stats.get("transaction_memos"):
                                            regular_memo_list = tx_stats.get("transaction_memos", [])
                                            if regular_memo_list and len(regular_memo_list) > 0:
                                                final_transaction_memos = regular_memo_list
                                                logger.info(f"ℹ️ FALLBACK: No special wallet memos, using {len(final_transaction_memos)} regular transaction memos")
                                                if final_transaction_memos:
                                                    logger.info(f"ℹ️ First regular memo: '{final_transaction_memos[0].get('memo_data', '')}' from tx {final_transaction_memos[0].get('tx_hash', 'unknown')}")
                                        
                                        # Log final memo counts
                                        logger.info(f"📊 FINAL MEMO COUNTS: special={len(final_special_wallet_memos)}, regular={len(final_transaction_memos)}")
                                        
                                        if not final_special_wallet_memos and not final_transaction_memos:
                                            logger.info("🚫 NO MEMOS: Neither special wallet nor transaction memos found")  
                                        # Create the final data structure with the chosen memos
                                        # Final data structure with carefully chosen memos
                                        tx_details = {
                                            "transaction_types": tx_stats["transaction_types"],
                                            "currencies": tx_stats.get("currencies", {}),
                                            "largest_payment": float(tx_stats.get("largest_payment", 0)),
                                            "total_xrp_transferred": float(tx_stats.get("total_xrp_transferred", 0)),
                                            "total_fees": float(tx_stats.get("total_fees", 0)),
                                            "significant_accounts": tx_stats.get("active_accounts", [])[:5] if "active_accounts" in tx_stats else [],
                                            "detailed_transactions": tx_stats.get("sample_transactions", [])[:10] if "sample_transactions" in tx_stats else [],
                                            
                                            # Special wallet flags
                                            "special_wallet_received_xrp": special_wallet_received,
                                            "special_wallet_received_exact_amount": tx_stats.get("special_wallet_received_exact_amount", False),
                                            "special_wallet_received_cat_amount": tx_stats.get("special_wallet_received_cat_amount", False),
                                            
                                            # Memo data - CAREFULLY segregated
                                            "transaction_memos": final_transaction_memos,  # Regular transaction memos
                                            "special_wallet_memos": final_special_wallet_memos,  # Special wallet memos
                                            "has_special_wallet_memo": len(final_special_wallet_memos) > 0  # Set this based on actual memo presence
                                        }
                                        
                                        # Sanity check - should never have both kinds of memos
                                        if len(final_transaction_memos) > 0 and len(final_special_wallet_memos) > 0:
                                            logger.error("⛔ ERROR: Both memo types are populated! This should never happen!")
                                            logger.error(f"⛔ CONFLICT: {len(final_special_wallet_memos)} special wallet memos AND {len(final_transaction_memos)} regular memos")
                                            
                                            # Log the conflicting memos
                                            for i, memo in enumerate(final_special_wallet_memos):
                                                logger.error(f"⛔ Special wallet memo #{i+1}: '{memo.get('memo_data', '')}' from tx {memo.get('tx_hash', 'unknown')}")
                                            
                                            for i, memo in enumerate(final_transaction_memos[:3]):  # Log up to 3
                                                logger.error(f"⛔ Regular memo #{i+1}: '{memo.get('memo_data', '')}' from tx {memo.get('tx_hash', 'unknown')}")
                                            
                                            # Force prioritize special wallet memos
                                            tx_details["transaction_memos"] = []
                                            logger.error("⛔ RESOLUTION: Cleared transaction_memos to prioritize special wallet memos")
                                        
                                        # Log if special wallet received XRP
                                        if tx_stats.get("special_wallet_received_xrp", False):
                                            logger.info(f"SPECIAL WALLET RECEIVED XRP IN LEDGER #{ledger_index}!")
                                        
                                        # Log if special wallet received exactly 0.00101 XRP
                                        if tx_stats.get("special_wallet_received_exact_amount", False):
                                            logger.info(f"SPECIAL WALLET RECEIVED EXACTLY 0.00101 XRP IN LEDGER #{ledger_index}!")
                                        
                                        # Log if special wallet received exactly 0.0011 XRP (cat animation)
                                        if tx_stats.get("special_wallet_received_cat_amount", False):
                                            logger.info(f"SPECIAL WALLET RECEIVED EXACTLY 0.0011 XRP IN LEDGER #{ledger_index}! - SPINNING CAT ACTIVATED!")
                                        
                                        # Log memos based on priority
                                        if has_special_wallet_memo and special_wallet_memos:
                                            # Log only special wallet memos when they exist
                                            logger.info(f"Found {len(special_wallet_memos)} SPECIAL WALLET memos in ledger #{ledger_index}")
                                            for memo in special_wallet_memos:
                                                logger.info(f"SPECIAL WALLET MEMO in transaction {memo.get('tx_hash', '')[:10]}: {memo.get('memo_data', '')}")
                                        elif tx_stats.get("transaction_memos", []):
                                            # Only log regular memos if no special wallet memos exist
                                            logger.info(f"Found {len(tx_stats.get('transaction_memos', []))} regular memos in ledger #{ledger_index}")
                                            for memo in tx_stats.get("transaction_memos", []):
                                                logger.info(f"Regular memo in transaction {memo.get('tx_hash', '')[:10]}: {memo.get('memo_data', '')}")
                                        
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
                        
                        try:
                            # Thread-safe approach to emit Socket.IO events from background threads
                            def emit_with_app_context(data, ledger_idx):
                                with app.app_context():
                                    # Using engineio's internal async mode to properly handle thread-safe emits
                                    socketio.emit('new_block', data, namespace='/', broadcast=True)
                                    logger.debug(f"Emitted ledger #{ledger_idx} data to connected clients via thread-safe method")
                            
                            # Use socketio's proper thread handling
                            socketio.start_background_task(emit_with_app_context, ledger_info, ledger_index)
                            
                        except Exception as emit_error:
                            logger.error(f"Error emitting event: {emit_error}", exc_info=True)
                
        except Exception as e:
            # Handle WebSocket connection errors
            logger.error(f"Error in XRPL listener: {str(e)}", exc_info=True)
            consecutive_errors += 1
            
            # Notify clients about the disconnection
            socketio.emit('xrpl_connection_status', {
                'status': 'disconnected',
                'error': str(e),
                'url': current_url,
                'timestamp': datetime.now().isoformat(),
                'reconnect_delay': reconnect_delay
            })
            
            # Switch to next URL after multiple consecutive errors on the same endpoint
            if consecutive_errors >= max_consecutive_errors:
                logger.warning(f"Switching XRPL endpoint after {consecutive_errors} consecutive errors")
                current_url_index = (current_url_index + 1) % len(urls)
                consecutive_errors = 0  # Reset error counter when switching endpoints
            
            # Use exponential backoff for reconnection attempts
            logger.info(f"Reconnecting in {reconnect_delay} seconds...")
            time.sleep(reconnect_delay)
            reconnect_delay = min(reconnect_delay * 2, max_reconnect_delay)

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
    
    # Determine if we actually have a live connection to XRPL
    xrpl_thread_alive = xrpl_thread is not None and xrpl_thread.is_alive()
    client_connected = client is not None
    
    # Send response heartbeat back to confirm server is alive
    socketio.emit('heartbeat_response', {
        'server_time': datetime.now().isoformat(),
        'client_time': data.get('timestamp'),
        'xrpl_thread_alive': xrpl_thread_alive,
        'xrpl_connected': client_connected,
        'uptime': int(time.time() - server_start_time) if 'server_start_time' in globals() else 0
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

def stop_xrpl_thread():
    """Stop the XRPL listener thread."""
    global xrpl_thread, running
    
    logger.info("Stopping XRPL listener thread...")
    running = False
    
    if xrpl_thread and xrpl_thread.is_alive():
        logger.debug("Waiting for XRPL thread to terminate...")
        xrpl_thread.join(timeout=5.0)
        logger.info("XRPL thread stopped")

def start_xrpl_thread():
    """Start the XRPL listener thread with auto-reconnection capabilities."""
    global xrpl_thread, running
    
    if xrpl_thread and xrpl_thread.is_alive():
        logger.warning("XRPL listener thread is already running")
        return
    
    running = True
    xrpl_thread = Thread(target=xrpl_listener, name="XRPL_Listener")
    xrpl_thread.daemon = True
    xrpl_thread.start()
    
    # Start a watchdog thread to monitor and restart the XRPL thread if it dies
    watchdog_thread = Thread(target=xrpl_watchdog, name="XRPL_Watchdog")
    watchdog_thread.daemon = True
    watchdog_thread.start()
    
    logger.info("Started XRPL listener thread with auto-reconnection and watchdog monitoring")

def xrpl_watchdog():
    """Monitor the XRPL listener thread and restart it if needed."""
    global xrpl_thread, running
    
    check_interval = 5  # Check every 5 seconds
    restart_cooldown = 30  # Minimum time between restarts to prevent rapid cycling
    last_restart = 0
    
    logger.info("XRPL watchdog started")
    
    while running:
        time.sleep(check_interval)
        
        # Check if thread is dead but should be running
        if running and (xrpl_thread is None or not xrpl_thread.is_alive()):
            current_time = time.time()
            time_since_restart = current_time - last_restart
            
            # Prevent too frequent restarts
            if time_since_restart > restart_cooldown:
                logger.warning("XRPL listener thread is not running but should be. Restarting...")
                
                # Create a new thread (don't call start_xrpl_thread to avoid creating multiple watchdogs)
                xrpl_thread = Thread(target=xrpl_listener, name="XRPL_Listener_Restarted")
                xrpl_thread.daemon = True
                xrpl_thread.start()
                
                last_restart = current_time
                logger.info("XRPL thread restarted by watchdog")
                
                # Notify clients about the restart
                socketio.emit('xrpl_connection_status', {
                    'status': 'restarted',
                    'timestamp': datetime.now().isoformat()
                })
            else:
                logger.warning(f"XRPL thread restart needed but throttled (last restart was {time_since_restart:.1f}s ago)")

def get_ledger_transactions(client, ledger_hash):
    """Fetch all transactions for a given ledger."""
    try:
        # First, check if there are transactions in this ledger
        request = Ledger(ledger_hash=ledger_hash, transactions=True, expand=True)
        logger.debug(f"Requesting ledger data for hash {ledger_hash[:10]}...")
        
        # Safe way to handle the request that works with eventlet
        try:
            # Try to use the sync method directly
            response = client.request(request)
        except RuntimeError as re:
            # If we get a RuntimeError about running event loop, skip the transactions
            if "cannot be called from a running event loop" in str(re):
                logger.warning("Skipping transaction fetch due to eventlet/asyncio conflict")
                return []
            else:
                raise
            
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

if __name__ == '__main__':
    try:
        # Record server start time for uptime tracking
        server_start_time = time.time()
        
        logger.info("Starting XRPL listener thread")
        start_xrpl_thread()
        
        # Get port from environment variable for Railway deployment
        port = int(os.environ.get('PORT', 8000))
        
        logger.info(f"Starting Flask server on port {port}")
        socketio.run(app, host='0.0.0.0', port=port, debug=False, allow_unsafe_werkzeug=True)
    except KeyboardInterrupt:
        logger.info("Keyboard interrupt received. Shutting down...")
        stop_xrpl_thread()
    except Exception as e:
        logger.error(f"Error in main: {e}")
        stop_xrpl_thread()
