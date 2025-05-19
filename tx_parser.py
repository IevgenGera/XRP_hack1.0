"""
XRP Transaction Parser
This script analyzes XRP Ledger transactions and extracts useful information.
"""

import json
import time
import logging
import re
from datetime import datetime
from decimal import Decimal, DecimalException
from collections import defaultdict

# Transaction type mapping for more readable names
TX_TYPE_NAMES = {
    "Payment": "Payment",
    "OfferCreate": "Offer Create (DEX)",
    "OfferCancel": "Offer Cancel (DEX)",
    "TrustSet": "Trust Line Set",
    "EscrowCreate": "Escrow Create",
    "EscrowFinish": "Escrow Finish",
    "EscrowCancel": "Escrow Cancel",
    "PaymentChannelCreate": "Payment Channel Create",
    "PaymentChannelFund": "Payment Channel Fund",
    "PaymentChannelClaim": "Payment Channel Claim",
    "AccountSet": "Account Settings",
    "AccountDelete": "Account Delete",
    "SetRegularKey": "Set Regular Key",
    "SignerListSet": "Signer List Set",
    "TicketCreate": "Ticket Create",
    "NFTokenMint": "NFT Mint",
    "NFTokenBurn": "NFT Burn",
    "NFTokenCreateOffer": "NFT Create Offer",
    "NFTokenCancelOffer": "NFT Cancel Offer",
    "NFTokenAcceptOffer": "NFT Accept Offer",
}

def drops_to_xrp(drops):
    """Convert drops to XRP."""
    if not drops:
        return 0
    try:
        # 1 XRP = 1,000,000 drops
        return Decimal(drops) / Decimal("1000000")
    except (ValueError, TypeError):
        return 0

def get_transaction_type(tx):
    """Get a human-readable transaction type."""
    if not isinstance(tx, dict):
        print(f"[TX_PARSER] Transaction is not a dict: {type(tx)}")
        return "Unknown"
    
    # Print debugging info about the transaction structure
    print(f"[TX_PARSER] Transaction keys: {list(tx.keys())}")
    
    # Try to get TransactionType directly
    if "TransactionType" in tx:
        tx_type = tx.get("TransactionType")
        print(f"[TX_PARSER] Found direct TransactionType: {tx_type}")
        return TX_TYPE_NAMES.get(tx_type, tx_type)
    
    # Check in tx_json (the main structure from XRPL API responses)
    if "tx_json" in tx and isinstance(tx["tx_json"], dict):
        if "TransactionType" in tx["tx_json"]:
            tx_type = tx["tx_json"].get("TransactionType")
            print(f"[TX_PARSER] Found TransactionType in tx_json: {tx_type}")
            return TX_TYPE_NAMES.get(tx_type, tx_type)
    
    # Check other nested locations for TransactionType
    for location in ["tx", "transaction", "meta"]:
        if location in tx and isinstance(tx[location], dict) and "TransactionType" in tx[location]:
            tx_type = tx[location].get("TransactionType")
            print(f"[TX_PARSER] Found TransactionType in {location}: {tx_type}")
            return TX_TYPE_NAMES.get(tx_type, tx_type)
    
    print(f"[TX_PARSER] Could not find TransactionType in transaction")
    return "Unknown"

def get_transaction_result(tx):
    """Get the transaction result."""
    if not isinstance(tx, dict):
        return "Unknown"
    
    # Check meta for result (XRPL API format)
    if "meta" in tx and isinstance(tx["meta"], dict):
        result = tx["meta"].get("TransactionResult")
        if result:
            return result
    
    # Check metadata for result (another format)
    if "metadata" in tx and isinstance(tx["metadata"], dict):
        result = tx["metadata"].get("TransactionResult")
        if result:
            return result
    
    # For simple transactions
    return tx.get("TransactionResult", "Unknown")

def get_fee(tx):
    """Get the transaction fee in XRP."""
    if not isinstance(tx, dict):
        return Decimal('0')
    
    # Check if we have a tx_json field (XRPL API format)
    if "tx_json" in tx and isinstance(tx["tx_json"], dict):
        tx_data = tx["tx_json"]
    else:
        tx_data = tx
    
    # Look for Fee in the transaction
    if "Fee" in tx_data:
        # Fee is in drops (1 XRP = 1,000,000 drops)
        fee_drops = tx_data["Fee"]
        if isinstance(fee_drops, str):
            try:
                fee_drops = int(fee_drops)
            except (ValueError, TypeError):
                return Decimal('0')
        return Decimal(str(fee_drops)) / Decimal('1000000')
    
    return Decimal('0')

def get_timestamp(tx):
    """Get the transaction timestamp."""
    if not isinstance(tx, dict) or "date" not in tx:
        return None
    
    # XRPL timestamps are seconds since the "Ripple Epoch" (Jan 1, 2000)
    ripple_epoch = 946684800  # Seconds between Unix Epoch and Ripple Epoch
    unix_time = ripple_epoch + tx.get("date", 0)
    
    return datetime.fromtimestamp(unix_time).strftime("%Y-%m-%d %H:%M:%S")

def get_amount_info(tx):
    """Extract amount information from a payment transaction."""
    amount_info = {
        "currency": "XRP",
        "value": 0,
        "issuer": ""
    }
    
    if not isinstance(tx, dict) or get_transaction_type(tx) != "Payment":
        return amount_info
    
    if "Amount" in tx:
        amount = tx["Amount"]
        
        # XRP amount (string of drops)
        if isinstance(amount, str):
            amount_info["value"] = drops_to_xrp(amount)
        
        # Issued currency
        elif isinstance(amount, dict) and "currency" in amount:
            amount_info["currency"] = amount.get("currency", "")
            amount_info["value"] = Decimal(amount.get("value", "0"))
            amount_info["issuer"] = amount.get("issuer", "")
    
    return amount_info

def extract_participants(tx):
    """Extract sender and receiver from a transaction."""
    participants = {
        "sender": tx.get("Account", ""),
        "receiver": ""
    }
    
    # For payments, set the receiver
    if get_transaction_type(tx) == "Payment" and "Destination" in tx:
        participants["receiver"] = tx["Destination"]
    
    return participants

def extract_memo(tx):
    """Extract memo information from a transaction."""
    memos = []
    try:
        # Check if tx has Memos field and process it
        if "Memos" in tx and isinstance(tx["Memos"], list):
            for memo_obj in tx["Memos"]:
                if "Memo" in memo_obj and isinstance(memo_obj["Memo"], dict):
                    memo_data = memo_obj["Memo"].get("MemoData", "")
                    memo_type = memo_obj["Memo"].get("MemoType", "")
                    memo_format = memo_obj["Memo"].get("MemoFormat", "")
                    
                    # If MemoData is hex encoded, convert to text
                    if memo_data and all(c in '0123456789ABCDEFabcdef' for c in memo_data):
                        try:
                            # Try to convert from hex to text
                            memo_data = bytes.fromhex(memo_data).decode('utf-8')
                        except Exception as e:
                            print(f"[TX_PARSER] Error decoding memo data: {e}")
                    
                    memos.append({
                        "data": memo_data,
                        "type": memo_type,
                        "format": memo_format
                    })
        
        # Also check tx_json if it exists
        if "tx_json" in tx and isinstance(tx["tx_json"], dict) and "Memos" in tx["tx_json"]:
            for memo_obj in tx["tx_json"]["Memos"]:
                if "Memo" in memo_obj and isinstance(memo_obj["Memo"], dict):
                    memo_data = memo_obj["Memo"].get("MemoData", "")
                    memo_type = memo_obj["Memo"].get("MemoType", "")
                    memo_format = memo_obj["Memo"].get("MemoFormat", "")
                    
                    # If MemoData is hex encoded, convert to text
                    if memo_data and all(c in '0123456789ABCDEFabcdef' for c in memo_data):
                        try:
                            # Try to convert from hex to text
                            memo_data = bytes.fromhex(memo_data).decode('utf-8')
                        except Exception as e:
                            print(f"[TX_PARSER] Error decoding memo data: {e}")
                    
                    memos.append({
                        "data": memo_data,
                        "type": memo_type,
                        "format": memo_format
                    })
    except Exception as e:
        print(f"[TX_PARSER] Error extracting memos: {e}")
    
    return memos

def parse_transaction(transaction):
    """Parse a transaction from the XRP ledger."""
    if not isinstance(transaction, dict):
        return {}  # Not a valid transaction
    
    # Create a copy to avoid modifying the original
    tx = transaction.copy()
    
    # Use tx_json if available (sometimes transactions are wrapped)
    if 'tx_json' in tx:
        tx = tx['tx_json']
    
    # Store hash for tracing purposes
    tx_hash = tx.get('hash', 'unknown_hash')
    print(f"[TX_PARSER] PARSING TRANSACTION {tx_hash}")
    
    # DEBUG: Print key transaction properties for memo debugging
    print(f"[TX_PARSER] TRANSACTION KEYS: {list(tx.keys())}")
    if 'Destination' in tx:
        print(f"[TX_PARSER] 🔍 DESTINATION: {tx.get('Destination')}")
    if 'Memos' in tx:
        print(f"[TX_PARSER] 📝 MEMOS FOUND: {len(tx.get('Memos', []))}")
        print(f"[TX_PARSER] 📝 MEMOS CONTENT: {json.dumps(tx.get('Memos'), indent=2)[:500]}")
    
    # Basic transaction information
    tx_info = {
        'type': tx.get('TransactionType', 'Unknown'),
        'hash': tx_hash,
        'sequence': tx.get('Sequence', 0),
        'result': transaction.get('meta', {}).get('TransactionResult', ''),
        'date': tx.get('date', ''),
        'fee': int(tx.get('Fee', 0)) / 1000000  # Convert drops to XRP
    }
    
    # Debug key transaction fields
    print(f"[TX_PARSER] Transaction type: {tx_info['type']}")
    if 'Destination' in tx:
        print(f"[TX_PARSER] Destination: {tx.get('Destination')}")
    if 'Account' in tx:
        print(f"[TX_PARSER] Account (sender): {tx.get('Account')}")
    
    # Extract memo fields - PROPERLY HANDLE RAW XRPL FORMAT WITH DETAILED LOGGING
    tx_info['memos'] = []
    
    if 'Memos' in tx and isinstance(tx['Memos'], list):
        memos_list = tx['Memos']
        print(f"[TX_PARSER] 📝 Found {len(memos_list)} Memos in transaction {tx_hash}")
        print(f"[TX_PARSER] 📝 Memos list type: {type(tx['Memos'])}")
        
        # Dump entire memos structure for debug
        try:
            memo_dump = json.dumps(tx['Memos'], indent=2)
            print(f"[TX_PARSER] 📝 MEMOS STRUCTURE:\n{memo_dump}")
        except Exception as e:
            print(f"[TX_PARSER] Error dumping memos: {e}")
        
        for i, memo_obj in enumerate(memos_list):
            print(f"[TX_PARSER] 📝 Memo object {i+1} type: {type(memo_obj)}")
            
            if isinstance(memo_obj, dict):
                print(f"[TX_PARSER] 📝 Memo object {i+1} keys: {list(memo_obj.keys())}")
                
                if 'Memo' in memo_obj:
                    memo = memo_obj['Memo']
                    print(f"[TX_PARSER] 📝 Processing memo {i+1}/{len(memos_list)}")
                    print(f"[TX_PARSER] 📝 Memo content: {memo}")
                
                # Get the raw memo fields directly from the transaction with additional logging
                memo_type = memo.get('MemoType', '')
                memo_format = memo.get('MemoFormat', '')
                memo_data = memo.get('MemoData', '')
                
                print(f"[TX_PARSER] 📝 Raw memo fields - Type: '{memo_type}', Format: '{memo_format}', Data: '{memo_data}'")
                
                # Try to decode hex-encoded data if present
                if memo_data:
                    print(f"[TX_PARSER] 📝 Processing memo data of length {len(memo_data)}")
                    
                    try:
                        # Check if the data is hex-encoded
                        is_hex = all(c in '0123456789ABCDEFabcdef' for c in memo_data)
                        print(f"[TX_PARSER] 📝 Is memo data hex-encoded? {is_hex}")
                        
                        if is_hex:
                            try:
                                # Attempt to decode hex to UTF-8
                                decoded_data = bytes.fromhex(memo_data).decode('utf-8')
                                print(f"[TX_PARSER] 📝 Decoded hex memo: '{decoded_data}'")
                                memo_data = decoded_data
                            except Exception as e:
                                print(f"[TX_PARSER] 📝 Could not decode hex: {e}")
                        else:
                            print(f"[TX_PARSER] 📝 Memo is not hex-encoded, using as is")
                    except Exception as e:
                        print(f"[TX_PARSER] 📝 Error processing memo data: {e}")
                else:
                    print(f"[TX_PARSER] 📝 Empty memo data")
                
                print(f"[TX_PARSER] 📝 Final memo data: '{memo_data}'")
                
                # Create standardized memo object
                memo_item = {
                    'type': memo_type,
                    'format': memo_format,
                    'data': memo_data
                }
                
                # Store in transaction info
                tx_info['memos'].append(memo_item)
                print(f"[TX_PARSER] Added memo: {memo_item}")
    
    # For payments, set the receiver
    if tx_info['type'] == 'Payment':
        # Extract amount data
        amount_value = 0
        currency = 'Unknown'
        
        # Check for Amount field - can be in different formats
        if 'Amount' in tx:
            amount_field = tx['Amount']
            if isinstance(amount_field, dict):
                # Non-XRP payment or new format
                currency = amount_field.get('currency', 'Unknown')
                if currency == 'XRP':
                    # XRP in the new format with explicit currency
                    try:
                        amount_value = float(amount_field.get('value', 0))
                        print(f"[TX_PARSER] XRP payment (value format): {amount_value} XRP")
                    except (TypeError, ValueError) as e:
                        print(f"[TX_PARSER] Error parsing amount value: {e}")
                else:
                    # Non-XRP currency
                    try:
                        amount_value = float(amount_field.get('value', 0))
                        print(f"[TX_PARSER] Non-XRP payment: {amount_value} {currency}")
                    except (TypeError, ValueError) as e:
                        print(f"[TX_PARSER] Error parsing non-XRP amount: {e}")
                    
                tx_info['issuer'] = amount_field.get('issuer', '')
            elif isinstance(amount_field, (int, str)):
                # Traditional XRP payment (in drops)
                try:
                    currency = 'XRP'
                    amount_value = int(amount_field) / 1000000  # Convert drops to XRP
                    print(f"[TX_PARSER] XRP payment (drops format): {amount_value} XRP")
                except (TypeError, ValueError) as e:
                    print(f"[TX_PARSER] Error parsing XRP drops: {e}")
        
        # Also check DeliverMax for some payment types
        elif 'DeliverMax' in tx:
            deliver_max = tx['DeliverMax']
            if isinstance(deliver_max, dict) and deliver_max.get('currency') == 'XRP':
                try:
                    currency = 'XRP'
                    amount_value = float(deliver_max.get('value', 0))
                    print(f"[TX_PARSER] XRP payment via DeliverMax: {amount_value} XRP")
                except (TypeError, ValueError) as e:
                    print(f"[TX_PARSER] Error parsing DeliverMax: {e}")
        
        # Set the extracted values
        tx_info['currency'] = currency
        tx_info['amount'] = amount_value
        
        # Extract sender and receiver
        tx_info['sender'] = tx.get('Account', '')
        tx_info['receiver'] = tx.get('Destination', '')
        
        # Special debug for payments to our special wallet
        if tx_info['receiver'] == "ra22VZUKQbznAAQooPYffPPXs4MUFwqVeH":
            print(f"[TX_PARSER] PAYMENT TO SPECIAL WALLET: {amount_value} {currency}")
            if tx_info.get('memos'):
                for memo in tx_info['memos']:
                    print(f"[TX_PARSER] SPECIAL WALLET MEMO: {memo.get('data', '')}")
    
    return tx_info

def format_tx_info(tx_info):
    """Format transaction information for display."""
    output = []
    output.append(f"Transaction Type: {tx_info['type']}")
    output.append(f"Hash: {tx_info['hash']}")
    output.append(f"Result: {'Success' if tx_info['success'] else 'Failed'} ({tx_info['result']})")
    output.append(f"Fee: {tx_info['fee']} XRP")
    
    if tx_info['timestamp']:
        output.append(f"Time: {tx_info['timestamp']}")
    
    output.append(f"Sender: {tx_info['sender']}")
    
    if tx_info['receiver']:
        output.append(f"Receiver: {tx_info['receiver']}")
    
    if tx_info['type'] == "Payment":
        if tx_info['currency'] == "XRP":
            output.append(f"Amount: {tx_info['amount']} XRP")
        else:
            output.append(f"Amount: {tx_info['amount']} {tx_info['currency']}")
            output.append(f"Issuer: {tx_info['issuer']}")
    
    if tx_info['memos']:
        output.append("Memos:")
        for memo in tx_info['memos']:
            output.append(f"  - Data: {memo['data']}")
            output.append(f"  - Type: {memo['type']}")
            output.append(f"  - Format: {memo['format']}")
    
    return "\n".join(output)

def analyze_block_transactions(transactions):
    """Analyze a list of transactions from a block."""
    print(f"[TX_PARSER] Analyzing {len(transactions)} transactions in block")
    
    # Debug transactions structure
    if len(transactions) > 0:
        print(f"[TX_PARSER] First transaction type: {type(transactions[0])}")
        if isinstance(transactions[0], dict):
            print(f"[TX_PARSER] First transaction keys: {list(transactions[0].keys())}")
    
    stats = {
        "transaction_count": len(transactions),
        "transaction_types": {},
        "currencies": {},
        "total_xrp_transferred": Decimal(0),
        "largest_payment": Decimal(0),
        "total_fees": Decimal(0),
        "sample_transactions": [],  # Store a few sample parsed transactions
        "active_accounts": [],     # Track active accounts
        "special_wallet_received_xrp": False,  # Flag for the special wallet receiving XRP
        "special_wallet_received_exact_amount": False,  # Flag for the special wallet receiving exactly 0.00101 XRP
        "special_wallet_received_cat_amount": False,  # Flag for the special wallet receiving exactly 0.0011 XRP (cat animation)
        "transaction_memos": [],    # Store memos from transactions
        "special_wallet_memos": [],  # Track memos specifically sent to the special wallet
        "has_special_wallet_memo": False  # Flag to indicate if special wallet memos are present
    }
    
    # The special wallet address we're tracking
    SPECIAL_WALLET = "ra22VZUKQbznAAQooPYffPPXs4MUFwqVeH"
    
    # Special amount to track (in XRP)
    SPECIAL_AMOUNT_XRP = Decimal('0.00101')
    SPECIAL_AMOUNT_DROPS = 1010  # 0.00101 XRP in drops (1 XRP = 1,000,000 drops)
    SPECIAL_AMOUNT_XRP_CAT = Decimal('0.0011')
    SPECIAL_AMOUNT_DROPS_CAT = 1100  # 0.0011 XRP in drops (1 XRP = 1,000,000 drops)
    
    # Track accounts and their frequency
    account_counts = {}
    
    # Process each transaction
    for i, tx in enumerate(transactions):
        print(f"[TX_PARSER] Processing transaction {i+1}/{len(transactions)}")
        
        # Debug transaction before parsing
        tx_hash = "Unknown"
        if isinstance(tx, dict):
            tx_hash = tx.get("hash", tx.get("id", "Unknown"))
            print(f"[TX_PARSER] Transaction hash: {tx_hash}")
        
        # Parse the transaction
        try:
            tx_info = parse_transaction(tx)
            print(f"[TX_PARSER] Successfully parsed transaction of type: {tx_info.get('type', 'Unknown')}")
            
            # Very simple check for special wallet payment - ANY transaction to the special wallet
            is_special_wallet_payment = False
            
            # SIMPLE CHECK: If transaction is to special wallet, mark it as special
            if tx_info.get('receiver') == SPECIAL_WALLET or tx.get('Destination') == SPECIAL_WALLET:
                is_special_wallet_payment = True
                stats["special_wallet_received_xrp"] = True
                print(f"[TX_PARSER] FOUND PAYMENT TO SPECIAL WALLET: {tx_hash}")
                
                # MARK ALL MEMOS IN THIS TRANSACTION AS SPECIAL - This is the key fix
                if tx_info.get('memos') and len(tx_info.get('memos')) > 0:
                    # Mark all memos from this transaction as special wallet memos
                    for memo in tx_info['memos']:
                        if memo.get('data', '').strip():
                            print(f"[TX_PARSER] MARKING MEMO AS SPECIAL: {memo.get('data')}")
                            special_wallet_memo = {
                                "tx_hash": tx_hash,
                                "memo_data": memo.get('data', '').strip(),
                                "memo_type": memo.get('type', ''),
                                "memo_format": memo.get('format', '')
                            }
                            stats["special_wallet_memos"] = [special_wallet_memo]  # Just keep one
                            stats["has_special_wallet_memo"] = True
                            print(f"[TX_PARSER] STORED SPECIAL WALLET MEMO: {memo.get('data')}")
                            break  # Just use the first valid memo
            
            # Simple memo handling - just add regular memos if not already processed as special
            if tx_info.get("memos") and len(tx_info.get("memos")) > 0 and not is_special_wallet_payment:
                memo_count = len(tx_info['memos'])
                print(f"[TX_PARSER] Found {memo_count} regular memos in transaction {tx_hash}")
                
                # Just add regular memos - special ones were already handled above
                for memo in tx_info["memos"]:
                    memo_with_tx = {
                        "tx_hash": tx_hash,
                        "memo_data": memo.get("data", ""),
                        "memo_type": memo.get("type", ""),
                        "memo_format": memo.get("format", "")
                    }
                    stats["transaction_memos"].append(memo_with_tx)
            
            # Update tracking for special wallet payments
            # We already processed memos above, this is just for updating payment flags
            if tx_info.get('type') == 'Payment' and tx_info.get('receiver') == SPECIAL_WALLET and tx_info.get('currency') == 'XRP':
                print(f"[TX_PARSER] SPECIAL WALLET RECEIVED XRP: {tx_info.get('amount')} XRP")
                
                # Check if exact amount using standard method
                try:
                    payment_amount = Decimal(str(tx_info.get('amount', '0')))
                    # Check for 0.00101 XRP
                    if abs(payment_amount - SPECIAL_AMOUNT_XRP) < Decimal('0.000001'):  # Allow tiny rounding differences
                        print(f"[TX_PARSER] SPECIAL WALLET RECEIVED EXACTLY {SPECIAL_AMOUNT_XRP} XRP (standard parser)!")
                        stats['special_wallet_received_exact_amount'] = True
                    # Check for 0.0011 XRP (cat animation)
                    elif abs(payment_amount - SPECIAL_AMOUNT_XRP_CAT) < Decimal('0.000001'):  # Allow tiny rounding differences
                        print(f"[TX_PARSER] SPECIAL WALLET RECEIVED EXACTLY {SPECIAL_AMOUNT_XRP_CAT} XRP (standard parser) - cat animation!")
                        stats['special_wallet_received_cat_amount'] = True
                except (ValueError, TypeError, DecimalException) as e:
                    print(f"[TX_PARSER] Error checking exact amount: {e}")
            
            # Also check raw transaction in case direct parsing missed it
            if isinstance(tx, dict):
                # Check tx_json if it exists
                tx_data = tx.get('tx_json', tx)  # Use tx_json if available, otherwise use tx
                
                # Check if Destination is our special wallet
                if tx_data.get('Destination') == SPECIAL_WALLET:
                    print(f"[TX_PARSER] SPECIAL WALLET IS DESTINATION: {tx_data.get('hash', 'Unknown hash')}")
                    stats['special_wallet_received_xrp'] = True
                    
                    # Check if exact amount using standard method
                    try:
                        payment_amount = Decimal(str(tx_info.get('amount', '0')))
                        # Check for 0.00101 XRP
                        if abs(payment_amount - SPECIAL_AMOUNT_XRP) < Decimal('0.000001'):  # Allow tiny rounding differences
                            print(f"[TX_PARSER] SPECIAL WALLET RECEIVED EXACTLY {SPECIAL_AMOUNT_XRP} XRP (standard parser)!")
                            stats['special_wallet_received_exact_amount'] = True
                        # Check for 0.0011 XRP (cat animation)
                        elif abs(payment_amount - SPECIAL_AMOUNT_XRP_CAT) < Decimal('0.000001'):  # Allow tiny rounding differences
                            print(f"[TX_PARSER] SPECIAL WALLET RECEIVED EXACTLY {SPECIAL_AMOUNT_XRP_CAT} XRP (standard parser) - cat animation!")
                            stats['special_wallet_received_cat_amount'] = True
                    except (ValueError, TypeError, DecimalException) as e:
                        print(f"[TX_PARSER] Error checking exact amount: {e}")
                
                # Also check raw transaction in case direct parsing missed it
                if isinstance(tx, dict):
                    # Check tx_json if it exists
                    tx_data = tx.get('tx_json', tx)  # Use tx_json if available, otherwise use tx
                    
                    # Check if Destination is our special wallet
                    if tx_data.get('Destination') == SPECIAL_WALLET:
                        print(f"[TX_PARSER] SPECIAL WALLET IS DESTINATION: {tx_data.get('hash', 'Unknown hash')}")
                        stats['special_wallet_received_xrp'] = True
                        
                        # Additional check for exact amount using Amount field
                        try:
                            # Amount can be in different formats, handle both string and nested object
                            amount_field = tx_data.get('Amount')
                            if isinstance(amount_field, str):
                                amount_drops = Decimal(amount_field)
                                # Check for 0.00101 XRP
                                if amount_drops == SPECIAL_AMOUNT_DROPS:
                                    print(f"[TX_PARSER] SPECIAL WALLET RECEIVED EXACTLY {SPECIAL_AMOUNT_XRP} XRP (Amount field)!")
                                    stats['special_wallet_received_exact_amount'] = True
                                # Check for 0.0011 XRP (cat animation)
                                elif amount_drops == SPECIAL_AMOUNT_DROPS_CAT:
                                    print(f"[TX_PARSER] SPECIAL WALLET RECEIVED EXACTLY {SPECIAL_AMOUNT_XRP_CAT} XRP (Amount field) - cat animation!")
                                    stats['special_wallet_received_cat_amount'] = True
                            elif isinstance(amount_field, dict) and amount_field.get('currency') == 'XRP':
                                amount_xrp = Decimal(str(amount_field.get('value', '0')))
                                # Check for 0.00101 XRP
                                if abs(amount_xrp - SPECIAL_AMOUNT_XRP) < Decimal('0.000001'):
                                    print(f"[TX_PARSER] SPECIAL WALLET RECEIVED EXACTLY {SPECIAL_AMOUNT_XRP} XRP (Amount.value)!")
                                    stats['special_wallet_received_exact_amount'] = True
                                # Check for 0.0011 XRP (cat animation)
                                elif abs(amount_xrp - SPECIAL_AMOUNT_XRP_CAT) < Decimal('0.000001'):
                                    print(f"[TX_PARSER] SPECIAL WALLET RECEIVED EXACTLY {SPECIAL_AMOUNT_XRP_CAT} XRP (Amount.value) - cat animation!")
                                    stats['special_wallet_received_cat_amount'] = True
                        except (ValueError, TypeError, DecimalException) as e:
                            print(f"[TX_PARSER] Error checking Amount field: {e}")
                    
                    # Multiple redundant checks for meta data that shows the wallet balance increased
                    found_in_meta = False
                    try:
                        if 'meta' in tx and isinstance(tx['meta'], dict):
                            # Check AffectedNodes
                            if 'AffectedNodes' in tx['meta']:
                                for node in tx['meta']['AffectedNodes']:
                                    if 'ModifiedNode' in node:
                                        modified = node['ModifiedNode']
                                        # Check if this node represents our special wallet
                                        if modified.get('LedgerEntryType') == 'AccountRoot' and \
                                        modified.get('FinalFields', {}).get('Account') == SPECIAL_WALLET:
                                            # Check if Balance increased
                                            final_balance = Decimal(modified.get('FinalFields', {}).get('Balance', '0'))
                                            prev_balance = Decimal(modified.get('PreviousFields', {}).get('Balance', '0'))
                                            
                                            if final_balance > prev_balance:
                                                increase = final_balance - prev_balance
                                                print(f"[TX_PARSER] SPECIAL WALLET BALANCE INCREASED BY {increase} drops")
                                                stats['special_wallet_received_xrp'] = True
                                                found_in_meta = True
                                                
                                                # Check if the exact amount (0.00101 XRP = 1010 drops) was received
                                                if increase == SPECIAL_AMOUNT_DROPS:
                                                    print(f"[TX_PARSER] SPECIAL WALLET RECEIVED EXACTLY {SPECIAL_AMOUNT_XRP} XRP (meta)!")
                                                    stats['special_wallet_received_exact_amount'] = True
                                            
                                                # Check if the cat amount (0.0011 XRP = 1100 drops) was received
                                                if increase == SPECIAL_AMOUNT_DROPS_CAT:
                                                    print(f"[TX_PARSER] SPECIAL WALLET RECEIVED EXACTLY {SPECIAL_AMOUNT_XRP_CAT} XRP (cat animation)!")
                                                    stats['special_wallet_received_cat_amount'] = True
                            
                            # Also check the delivered_amount field in meta
                            if 'delivered_amount' in tx['meta'] and tx_data.get('Destination') == SPECIAL_WALLET:
                                delivered = tx['meta']['delivered_amount']
                                if isinstance(delivered, str):
                                    # Direct XRP amount in drops as string
                                    delivered_drops = Decimal(delivered)
                                    if delivered_drops == SPECIAL_AMOUNT_DROPS:
                                        print(f"[TX_PARSER] SPECIAL WALLET RECEIVED EXACTLY {SPECIAL_AMOUNT_XRP} XRP (delivered_amount)!")
                                        stats['special_wallet_received_exact_amount'] = True
                                elif isinstance(delivered, dict) and delivered.get('currency') == 'XRP':
                                    # XRP in a currency object
                                    delivered_xrp = Decimal(str(delivered.get('value', 0)))
                                    if abs(delivered_xrp - SPECIAL_AMOUNT_XRP) < Decimal('0.000001'):
                                        print(f"[TX_PARSER] SPECIAL WALLET RECEIVED EXACTLY {SPECIAL_AMOUNT_XRP} XRP (delivered_amount.value)!")
                                        stats['special_wallet_received_exact_amount'] = True
                        
                        # Extra safety check - if we found the special wallet received XRP in any of the checks
                        # Log what method detected it for debug purposes
                        if found_in_meta:
                            print(f"[TX_PARSER] Special wallet payment detected via meta data")
                    except Exception as meta_error:
                        print(f"[TX_PARSER] Error processing meta data: {meta_error}")
        except Exception as e:
            print(f"[TX_PARSER] Error parsing transaction: {e}")
            continue
        
        # Add to sample transactions list
        if len(stats["sample_transactions"]) < 10:
            stats["sample_transactions"].append(tx_info)
        
        # Track accounts
        if "sender" in tx_info:
            sender = tx_info["sender"]
            account_counts[sender] = account_counts.get(sender, 0) + 1
        if "receiver" in tx_info:
            receiver = tx_info["receiver"]
            account_counts[receiver] = account_counts.get(receiver, 0) + 1
        
        # Count transaction types
        tx_type = tx_info.get("type", "Unknown")
        stats["transaction_types"][tx_type] = stats["transaction_types"].get(tx_type, 0) + 1
        print(f"[TX_PARSER] Counted transaction type: {tx_type}")
        
        # Track fees - ensure both are Decimal type
        if "fee_xrp" in tx_info:
            # Convert fee to Decimal if it's not already
            if not isinstance(tx_info["fee_xrp"], Decimal):
                fee_xrp = Decimal(str(tx_info["fee_xrp"]))
            else:
                fee_xrp = tx_info["fee_xrp"]
            stats["total_fees"] += fee_xrp
            print(f"[TX_PARSER] Added fee: {fee_xrp} XRP, total now: {stats['total_fees']} XRP")
        
        # Track amounts for payments
        if tx_type == "Payment" and "amount" in tx_info:
            amount = tx_info["amount"]
            currency = tx_info.get("currency", "Unknown")
            
            # Count currencies
            if currency not in stats["currencies"]:
                stats["currencies"][currency] = 0
            stats["currencies"][currency] += 1
            
            # Track XRP amounts
            if currency == "XRP" and isinstance(amount, (int, float, Decimal, str)):
                # Convert to Decimal for precision
                if not isinstance(amount, Decimal):
                    try:
                        amount = Decimal(str(amount))
                    except (ValueError, TypeError):
                        print(f"[TX_PARSER] Warning: Could not convert amount to Decimal: {amount}")
                        continue
                        
                stats["total_xrp_transferred"] += amount
                print(f"[TX_PARSER] Added {amount} XRP to total transferred")
                
                # Track largest payment
                if amount > stats["largest_payment"]:
                    stats["largest_payment"] = amount
                    print(f"[TX_PARSER] New largest payment: {amount} XRP")
    
    return stats

def format_block_stats(stats):
    """Format block statistics for display."""
    output = []
    output.append(f"Block Summary:")
    output.append(f"Total Transactions: {stats['transaction_count']}")
    output.append(f"Successful: {stats.get('successful_txs', 0)}")
    output.append(f"Failed: {stats.get('failed_txs', 0)}")
    output.append(f"Total Fees: {stats.get('total_fees', Decimal(0)):.6f} XRP")
    
    output.append("\nTransaction Types:")
    for tx_type, count in stats["transaction_types"].items():
        output.append(f"  {tx_type}: {count}")
    
    if stats["currencies"]:
        output.append("\nCurrencies:")
        for currency, count in stats["currencies"].items():
            output.append(f"  {currency}: {count}")
    
    if stats["total_xrp_transferred"] > 0:
        output.append(f"\nXRP Transferred: {stats['total_xrp_transferred']:.2f} XRP")
        output.append(f"Largest Payment: {stats['largest_payment_xrp']:.2f} XRP")
    
    return "\n".join(output)

def fetch_latest_ledger_data():
    """Fetch the latest ledger data from the XRP Ledger."""
    import requests
    
    try:
        # Connect to XRPL public API
        response = requests.post(
            "https://s1.ripple.com:51234/",
            json={
                "method": "ledger",
                "params": [
                    {
                        "ledger_index": "validated",
                        "transactions": True,
                        "expand": True
                    }
                ]
            }
        )
        
        data = response.json()
        
        if "result" in data and "ledger" in data["result"]:
            ledger = data["result"]["ledger"]
            transactions = ledger.get("transactions", [])
            ledger_index = ledger.get("ledger_index")
            
            print(f"\nFetched ledger #{ledger_index} with {len(transactions)} transactions")
            return ledger_index, transactions
        else:
            print("Error fetching ledger data:", data)
            return None, []
    
    except Exception as e:
        print(f"Error connecting to XRP Ledger: {e}")
        return None, []


def fetch_transaction_by_hash(tx_hash):
    """Fetch a specific transaction by its hash."""
    import requests
    
    try:
        # Connect to XRPL public API
        response = requests.post(
            "https://s1.ripple.com:51234/",
            json={
                "method": "tx",
                "params": [
                    {
                        "transaction": tx_hash,
                        "binary": False
                    }
                ]
            }
        )
        
        data = response.json()
        
        if "result" in data and "validated" in data["result"]:
            return data["result"]
        else:
            print("Error fetching transaction:", data)
            return None
    
    except Exception as e:
        print(f"Error connecting to XRP Ledger: {e}")
        return None


# Simple XRP transaction parser - enter a hash below to fetch and analyze it

def main():
    """Parse and analyze an XRP Ledger transaction by its hash."""
    import sys
    
    # Get transaction hash from command line argument or input
    if len(sys.argv) > 1:
        # If provided as command line argument
        tx_hash = sys.argv[1]
    else:
        # Otherwise prompt for it
        tx_hash = input("Enter transaction hash to analyze: ")
    
    if not tx_hash or tx_hash.strip() == "":
        print("Error: No transaction hash provided.")
        return
    
    # Clean up any whitespace
    tx_hash = tx_hash.strip()
    
    print(f"Fetching transaction with hash: {tx_hash}")
    tx = fetch_transaction_by_hash(tx_hash)
    
    if not tx:
        print("Error: No transaction found with that hash.")
        return
    
    # Parse and display transaction details
    tx_info = parse_transaction(tx)
    
    print("\n=== Transaction Details ===")
    print(format_tx_info(tx_info))
    
    print("\n=== Transaction Type Analysis ===")
    tx_type = tx.get("TransactionType", "Unknown")
    print(f"Transaction Type: {tx_type}")
    
    # Display different details based on transaction type
    if tx_type == "Payment":
        print("\n=== Payment Details ===")
        try:
            amount = tx.get("Amount", "Unknown")
            if isinstance(amount, str) and amount.isdigit():
                # Convert drops to XRP
                amount_xrp = int(amount) / 1000000
                print(f"Amount: {amount_xrp} XRP ({amount} drops)")
            else:
                print(f"Amount: {amount}")
            
            print(f"From: {tx.get('Account', 'Unknown')}")
            print(f"To: {tx.get('Destination', 'Unknown')}")
            print(f"Fee: {int(tx.get('Fee', 0)) / 1000000} XRP")
        except Exception as e:
            print(f"Error parsing payment details: {e}")
    
    # Print other useful transaction metadata
    print("\n=== Transaction Metadata ===")
    result = tx.get("meta", {}).get("TransactionResult", "Unknown")
    print(f"Result: {result}")
    
    # If you want to see the full transaction data, uncomment this section
    # print("\n=== Raw Transaction Data ===")
    # print(json.dumps(tx, indent=2))
    
    

if __name__ == "__main__":
    main()
