"""
XRPL Ledger Watcher
This script connects to the XRP Ledger mainnet via websocket and streams new ledger closes (blocks).
It extracts transaction data and calculates statistics for each block.
"""

import asyncio
import json
from datetime import datetime
from collections import defaultdict
from decimal import Decimal

from xrpl.clients import WebsocketClient
from xrpl.models import Subscribe, StreamParameter
from xrpl.models.requests import Ledger


# Function to format ledger data in a readable way
def format_ledger_info(ledger_info):
    """Format ledger information in a human-readable format."""
    if not ledger_info or "type" not in ledger_info:
        return "Invalid ledger data"
    
    if ledger_info["type"] != "ledgerClosed":
        return None
    
    timestamp = datetime.fromtimestamp(ledger_info.get("ledger_time", 0))
    formatted_time = timestamp.strftime("%Y-%m-%d %H:%M:%S")
    
    return (
        f"==== New Ledger Closed ====\n"
        f"Ledger Hash: {ledger_info.get('ledger_hash', 'N/A')}\n"
        f"Ledger Index: {ledger_info.get('ledger_index', 'N/A')}\n"
        f"Time: {formatted_time}\n"
        f"Txn Count: {ledger_info.get('txn_count', 0)}\n"
        f"Reserve Base: {ledger_info.get('reserve_base', 'N/A')} drops\n"
        f"Reserve Inc: {ledger_info.get('reserve_inc', 'N/A')} drops\n"
        f"Fee Base: {ledger_info.get('fee_base', 'N/A')}\n"
        f"Fee Ref: {ledger_info.get('fee_ref', 'N/A')}\n"
        f"============================"
    )


def get_transaction_type(tx):
    """Get the transaction type."""
    if not isinstance(tx, dict):
        return "Unknown"
    
    # If we're dealing with a detailed transaction response
    if "result" in tx and isinstance(tx["result"], dict):
        tx_obj = tx["result"]
        if "TransactionType" in tx_obj:
            return tx_obj["TransactionType"]
    
    # Handle other possible structures
    if "TransactionType" in tx:
        return tx["TransactionType"]
    
    # Look in nested structures
    nested_locations = ["tx", "transaction"]
    for loc in nested_locations:
        if loc in tx and isinstance(tx[loc], dict) and "TransactionType" in tx[loc]:
            return tx[loc]["TransactionType"]
    
    return "Unknown"


def get_amount_info(tx):
    """Extract amount information from a transaction."""
    # First normalize the transaction object
    if isinstance(tx, dict) and "result" in tx and isinstance(tx["result"], dict):
        tx = tx["result"]
    
    # Find Amount field
    amount = None
    possible_paths = [
        ["Amount"],  # Direct path
        ["tx", "Amount"],  # Nested in tx
        ["transaction", "Amount"],  # Nested in transaction
        ["metaData", "delivered_amount"],  # Sometimes in metaData
        ["meta", "delivered_amount"]  # Alternative metaData path
    ]
    
    # Try all possible paths
    for path in possible_paths:
        current = tx
        valid_path = True
        
        for key in path:
            if not isinstance(current, dict) or key not in current:
                valid_path = False
                break
            current = current[key]
        
        if valid_path:
            amount = current
            break
    
    # If still no amount found, return default
    if amount is None:
        # Check if this is a Payment type transaction
        tx_type = get_transaction_type(tx)
        if tx_type != "Payment":
            # For non-payment transactions, it's normal to have no amount
            return {"currency": "XRP", "value": Decimal(0)}
        else:
            print(f"Debug - Payment with no amount found: {json.dumps(tx)[:200]}...")
            return {"currency": "XRP", "value": Decimal(0)}
    
    # Handle complex amount objects (non-XRP currencies)
    if isinstance(amount, dict):
        currency = amount.get("currency", "Unknown")
        value = Decimal(amount.get("value", "0"))
        return {"currency": currency, "value": value}
    
    # Handle XRP amount (in drops, 1 XRP = 1,000,000 drops)
    try:
        if isinstance(amount, (str, int)):
            return {"currency": "XRP", "value": Decimal(amount) / Decimal(1000000)}
    except Exception as e:
        print(f"Error converting amount {amount}: {e}")
    
    return {"currency": "XRP", "value": Decimal(0)}


def calculate_block_stats(transactions):
    """Calculate statistics for a block based on its transactions."""
    if not transactions:
        return {"message": "No transactions in this block"}
    
    stats = {
        "transaction_count": len(transactions),
        "transaction_types": {},
        "total_volume": defaultdict(Decimal),
        "currency_count": defaultdict(int),
        "largest_transaction": {"currency": "", "value": Decimal(0), "tx_type": "", "hash": ""},
        "total_fees_xrp": Decimal(0)
    }
    
    for tx in transactions:
        # Extract normalized transaction data
        if isinstance(tx, dict) and "result" in tx and isinstance(tx["result"], dict):
            tx_data = tx["result"]
        else:
            tx_data = tx
        
        # Get transaction hash
        tx_hash = tx_data.get("hash", "Unknown")
        
        # Count transaction types
        tx_type = get_transaction_type(tx)
        stats["transaction_types"][tx_type] = stats["transaction_types"].get(tx_type, 0) + 1
        
        # Get fee
        fee = Decimal(0)
        fee_paths = [
            ["Fee"],
            ["tx", "Fee"],
            ["transaction", "Fee"]
        ]
        
        for path in fee_paths:
            current = tx_data
            valid_path = True
            
            for key in path:
                if not isinstance(current, dict) or key not in current:
                    valid_path = False
                    break
                current = current[key]
            
            if valid_path and (isinstance(current, str) or isinstance(current, int)):
                try:
                    fee = Decimal(current) / Decimal(1000000)  # Convert from drops to XRP
                    break
                except:
                    pass
        
        stats["total_fees_xrp"] += fee
        
        # Process transaction data
        amount_info = get_amount_info(tx)
        currency = amount_info["currency"]
        value = amount_info["value"]
        
        # Only process if there's a non-zero value
        if value > 0:
            # Update total volume and count for each currency
            stats["total_volume"][currency] += value
            stats["currency_count"][currency] += 1
            
            # Track largest transaction
            if value > stats["largest_transaction"]["value"]:
                stats["largest_transaction"] = {
                    "currency": currency,
                    "value": value,
                    "tx_type": tx_type,
                    "hash": tx_hash
                }
    
    # Determine most active currency by volume
    most_active_currency = ""
    highest_volume = Decimal(0)
    
    for currency, volume in stats["total_volume"].items():
        if volume > highest_volume:
            most_active_currency = currency
            highest_volume = volume
    
    stats["most_active_currency"] = most_active_currency
    
    return stats


def format_block_stats(stats, ledger_index):
    """Format block statistics in a human-readable way."""
    output = [
        f"\n==== Block {ledger_index} Statistics ====",
        f"Total Transactions: {stats['transaction_count']}"
    ]
    
    # Transaction types breakdown
    output.append("\nTransaction Types:")
    for tx_type, count in stats["transaction_types"].items():
        output.append(f"  - {tx_type}: {count}")
    
    # Volume statistics
    output.append("\nVolume Statistics:")
    for currency, volume in stats["total_volume"].items():
        output.append(f"  - {currency}: {volume:.6f} ({stats['currency_count'][currency]} transactions)")
    
    # Most active currency
    if stats["most_active_currency"]:
        most_active = stats["most_active_currency"]
        output.append(f"\nMost Active Currency: {most_active} - Volume: {stats['total_volume'][most_active]:.6f}")
    
    # Largest transaction
    if stats["largest_transaction"]["currency"]:
        lt = stats["largest_transaction"]
        output.append(f"\nLargest Transaction: {lt['value']:.6f} {lt['currency']} ({lt['tx_type']})")
    
    # Total fees
    output.append(f"\nTotal Fees Paid: {stats['total_fees_xrp']:.6f} XRP")
    output.append("==============================")
    
    return "\n".join(output)


def get_ledger_transactions(client, ledger_hash):
    """Fetch all transactions for a given ledger."""
    try:
        # First, check if there are transactions in this ledger
        request = Ledger(ledger_hash=ledger_hash, transactions=True, expand=True)
        response = client.request(request)
        
        if response.is_successful():
            result = response.result
            if "ledger" in result and "transactions" in result["ledger"]:
                transactions = result["ledger"]["transactions"]
                
                # Check if transactions is a list
                if not isinstance(transactions, list):
                    print(f"Unexpected transactions format: {type(transactions)}")
                    return []
                
                print(f"Found {len(transactions)} transactions in ledger")
                
                # Debug the first transaction if available
                if transactions:
                    print(f"Debug - Transaction format: {json.dumps(transactions[0], indent=2)[:300]}...")
                
                return transactions
            else:
                print("No transactions field in ledger result")
        else:
            print(f"Failed to fetch ledger: {response.result}")
        
        return []
    except Exception as e:
        print(f"Error fetching transactions: {e}")
        return []


def main():
    """Main function to connect to XRPL and stream ledger closures."""
    # XRP Ledger mainnet websocket URL
    mainnet_url = "wss://xrplcluster.com/"
    
    print("Connecting to XRP Ledger mainnet...")
    
    try:
        with WebsocketClient(mainnet_url) as client:
            print(f"Connected to {mainnet_url}")
            print("Subscribing to ledger stream...")
            
            # Subscribe to ledger stream
            subscribe_request = Subscribe(streams=[StreamParameter.LEDGER])
            client.send(subscribe_request)
            
            print("Waiting for ledger closures. Press Ctrl+C to exit.")
            
            for message in client:
                # Check if this is a ledger closed message
                if message and isinstance(message, dict) and message.get("type") == "ledgerClosed":
                    # Format and print the ledger information
                    ledger_info = format_ledger_info(message)
                    if ledger_info:
                        print(ledger_info)
                        
                        # Get the ledger hash and index
                        ledger_hash = message.get("ledger_hash")
                        ledger_index = message.get("ledger_index")
                        
                        # Fetch transactions for this ledger
                        print(f"Fetching transactions for ledger {ledger_index}...")
                        transactions = get_ledger_transactions(client, ledger_hash)
                        
                        # Calculate and display block statistics
                        if transactions:
                            print(f"Found {len(transactions)} transactions")
                            stats = calculate_block_stats(transactions)
                            formatted_stats = format_block_stats(stats, ledger_index)
                            print(formatted_stats)
                        else:
                            print("No transactions found in this ledger")
                            
    except KeyboardInterrupt:
        print("\nShutting down...")
    except Exception as e:
        print(f"An error occurred: {e}")


# This is not needed anymore as we're not using async


if __name__ == "__main__":
    main()