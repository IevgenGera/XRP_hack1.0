document.addEventListener('DOMContentLoaded', function() {
    console.log('DOM fully loaded');
    
    // Connect to SocketIO with reconnection options
    const socket = io({
        reconnection: true,
        reconnectionAttempts: Infinity,
        reconnectionDelay: 1000,
        reconnectionDelayMax: 5000,
        timeout: 20000
    });
    
    // Socket connection monitoring
    socket.on('connect', function() {
        console.log('Socket connected successfully');
        document.getElementById('connection-status').textContent = 'Connected';
        document.getElementById('connection-status').className = 'connected';
    });
    
    socket.on('disconnect', function() {
        console.log('Socket disconnected');
        document.getElementById('connection-status').textContent = 'Disconnected - Reconnecting...';
        document.getElementById('connection-status').className = 'disconnected';
    });
    
    socket.on('connect_error', function(error) {
        console.log('Connection error:', error);
        document.getElementById('connection-status').textContent = 'Connection Error';
        document.getElementById('connection-status').className = 'disconnected';
    });
    
    socket.on('reconnect', function(attemptNumber) {
        console.log('Reconnected after', attemptNumber, 'attempts');
        document.getElementById('connection-status').textContent = 'Reconnected';
        document.getElementById('connection-status').className = 'connected';
    });
    const animationContainer = document.getElementById('animation-container');
    const connectionStatus = document.getElementById('connection-status');
    const latestBlockInfo = document.getElementById('latest-block-info');
    
    // Create a test walker immediately
    setTimeout(function() {
        console.log('Creating test walker');
        createWalker();
    }, 1000);
    
    // Connection status handlers
    socket.on('connect', function() {
        connectionStatus.innerHTML = 'Connected to XRP Ledger';
        connectionStatus.style.color = '#4CAF50';
    });
    
    socket.on('disconnect', function() {
        connectionStatus.innerHTML = 'Disconnected from XRP Ledger';
        connectionStatus.style.color = '#F44336';
    });
    
    // New block handler - creates a new walker with size based on transaction count
    socket.on('new_block', function(data) {
        if (!data) {
            console.error('Received empty block data');
            return;
        }
        
        console.log('New block received:', data);
        
        // Update block info display
        updateBlockInfo(data);
        
        // 1. Check if specific wallet received EXACTLY 0.00101 XRP (highest priority)
        const specialWalletExactAmount = checkSpecificWalletReceivedExactAmount(data);
        
        // 2. Check if specific wallet received any XRP (high priority)
        const specialWalletReceived = checkSpecificWalletReceivedXRP(data);
        
        // 3. Check if there are any NFT mint transactions (medium priority)
        const hasNFTMint = checkForNFTMintTransactions(data);
        
        // Update payment tracker if special wallet received payments
        if (specialWalletExactAmount) {
            updatePaymentTracker(true); // Exact amount
        } else if (specialWalletReceived) {
            updatePaymentTracker(false); // Any amount
        }
        
        // Create a walker with appropriate attributes
        const txCount = data.txn_count || 0;
        createWalker(txCount, hasNFTMint, specialWalletReceived, specialWalletExactAmount);
    });
    
    // Function to check if specific wallet received EXACTLY 0.00101 XRP
    function checkSpecificWalletReceivedExactAmount(blockData) {
        // Use the flag directly from the backend
        if (blockData.tx_details && typeof blockData.tx_details.special_wallet_received_exact_amount === 'boolean') {
            const result = blockData.tx_details.special_wallet_received_exact_amount;
            if (result) {
                console.log('Backend detected special wallet received EXACTLY 0.00101 XRP in this block!');
            }
            return result;
        }
        return false;
    }
    
    // Function to check if specific wallet received XRP in any transaction
    function checkSpecificWalletReceivedXRP(blockData) {
        // Target wallet address
        const targetWallet = 'ra22VZUKQbznAAQooPYffPPXs4MUFwqVeH';
        
        // Use the flag directly from the backend if available
        if (blockData.tx_details && typeof blockData.tx_details.special_wallet_received_xrp === 'boolean') {
            // Use the flag set by the backend after detailed transaction analysis
            const result = blockData.tx_details.special_wallet_received_xrp;
            if (result) {
                console.log('Backend detected special wallet received XRP in this block!');
            }
            return result;
        }
        
        // Fallback method (less reliable) in case the flag isn't provided
        // Check if we have detailed transactions
        if (!blockData.tx_details || !blockData.tx_details.detailed_transactions) {
            return false;
        }
        
        // Loop through the detailed transactions
        const transactions = blockData.tx_details.detailed_transactions;
        
        // Look for Payment transactions to the target wallet
        return transactions.some(tx => {
            return (
                tx.type === 'Payment' && 
                tx.currency === 'XRP' && 
                tx.receiver === targetWallet
            );
        });
    }
    
    // Function to check if the block contains NFT mint transactions
    function checkForNFTMintTransactions(blockData) {
        // Check if we have transaction details
        if (!blockData.tx_details || !blockData.tx_details.transaction_types) {
            return false;
        }
        
        const txTypes = blockData.tx_details.transaction_types;
        
        // Look for NFT mint transaction types
        // XRPL has 'NFTokenMint' as the transaction type for minting NFTs
        return Object.keys(txTypes).some(type => {
            return type.includes('NFT') || type.includes('Token') || type.includes('Mint');
        });
    }
    
    function updateBlockInfo(blockData) {
        // Extract transaction details if available
        const txDetails = blockData.tx_details || {};
        const txTypes = txDetails.transaction_types || {};
        let txTypeHTML = '';
        
        // Generate HTML for transaction types
        for (const [type, count] of Object.entries(txTypes)) {
            txTypeHTML += `<div class="tx-type"><span>${type}:</span> ${count}</div>`;
        }
        
        // Generate HTML for XRP statistics if available
        let xrpHTML = '';
        if (txDetails.total_xrp_transferred) {
            xrpHTML = `
                <div class="xrp-info">
                    <div><strong>Total XRP:</strong> ${txDetails.total_xrp_transferred.toFixed(2)} XRP</div>
                    <div><strong>Largest Payment:</strong> ${txDetails.largest_payment.toFixed(2)} XRP</div>
                    <div><strong>Total Fees:</strong> ${txDetails.total_fees_xrp ? txDetails.total_fees_xrp.toFixed(6) : '0'} XRP</div>
                </div>
            `;
        }
        
        // Generate HTML for significant accounts if available
        let accountsHTML = '';
        if (txDetails.significant_accounts && txDetails.significant_accounts.length > 0) {
            accountsHTML = '<div class="accounts-header">Active Accounts:</div>';
            txDetails.significant_accounts.slice(0, 3).forEach(account => {
                accountsHTML += `<div class="account-item" title="${account.address}">r...${account.address.substr(-6)} (${account.frequency} txs)</div>`;
            });
        }
        
        // Generate HTML for detailed transactions if available
        let detailedTxHTML = '';
        if (txDetails.detailed_transactions && txDetails.detailed_transactions.length > 0) {
            detailedTxHTML = '<div class="detailed-tx-header">Sample Transactions:</div><div class="detailed-tx-list">';
            txDetails.detailed_transactions.slice(0, 3).forEach(tx => {
                let txDescription = tx.type;
                let txDetails = '';
                
                if (tx.type === 'Payment' && tx.amount && tx.currency) {
                    txDescription = `Payment: ${tx.amount.toFixed(2)} ${tx.currency}`;
                    if (tx.destination) {
                        txDetails = `To: r...${tx.destination.substr(-6)}`;
                    }
                }
                
                const resultClass = tx.success ? 'tx-success' : 'tx-failed';
                detailedTxHTML += `
                    <div class="tx-item ${resultClass}">
                        <div class="tx-desc">${txDescription}</div>
                        ${txDetails ? `<div class="tx-addr">${txDetails}</div>` : ''}
                        <div class="tx-hash" title="${tx.hash}">Hash: ${tx.hash.substr(0, 8)}...</div>
                    </div>
                `;
            });
            detailedTxHTML += '</div>';
        }
        
        // Update the info panel with all block and transaction data
        latestBlockInfo.innerHTML = `
            <div class="block-header">Ledger #${blockData.ledger_index}</div>
            <div class="block-basics">Transactions: ${blockData.txn_count}</div>
            <div class="block-time">Time: ${blockData.formatted_time}</div>
            ${txTypeHTML ? `<div class="tx-types-header">Transaction Types:</div>${txTypeHTML}` : ''}
            ${xrpHTML}
            ${accountsHTML}
            ${detailedTxHTML}
        `;
    }
    
    // Track the last time we created a walker (to prevent overlapping)
    let lastWalkerTime = 0;
    
    // Payment tracking variables
    let exactPaymentCount = 0;
    let anyPaymentCount = 0;
    let recentPayments = [];
    const MAX_PAYMENT_HISTORY = 10; // Maximum number of payments to keep in history
    
    // Function to update the payment tracker UI
    function updatePaymentTracker(isExactAmount = false) {
        const now = new Date();
        const timeString = now.toLocaleTimeString();
        const dateString = now.toLocaleDateString();
        
        // Update counters
        if (isExactAmount) {
            exactPaymentCount++;
            document.getElementById('exact-payment-count').textContent = exactPaymentCount;
        }
        anyPaymentCount++;
        document.getElementById('any-payment-count').textContent = anyPaymentCount;
        
        // Update last payment time
        document.getElementById('last-payment-time').textContent = `${dateString} ${timeString}`;
        
        // Add to payment history
        const payment = {
            time: timeString,
            date: dateString,
            isExact: isExactAmount
        };
        
        recentPayments.unshift(payment); // Add to beginning of array
        if (recentPayments.length > MAX_PAYMENT_HISTORY) {
            recentPayments.pop(); // Remove oldest entry
        }
        
        // Update payment history display
        updatePaymentHistoryDisplay();
        
        console.log(`Payment tracker updated: exact=${isExactAmount}, total exact=${exactPaymentCount}, total any=${anyPaymentCount}`);
    }
    
    // Function to update the payment history display
    function updatePaymentHistoryDisplay() {
        const paymentList = document.getElementById('payment-list');
        paymentList.innerHTML = '';
        
        recentPayments.forEach(payment => {
            const entry = document.createElement('div');
            entry.className = 'payment-entry' + (payment.isExact ? ' exact-amount' : '');
            
            const amountText = payment.isExact ? 'EXACTLY 0.00101 XRP' : 'XRP payment';
            entry.innerHTML = `
                <div>${amountText}</div>
                <div class="payment-time">${payment.date} ${payment.time}</div>
            `;
            
            paymentList.appendChild(entry);
        });
    }
    
    // Function to create a walker div with size based on transaction count
    function createWalker(txCount = 100, hasNFTMint = false, specialWalletReceived = false, specialWalletExactAmount = false) { // Default to 100 txns if not specified
        // Prevent overlapping by enforcing minimum time between walkers
        const now = Date.now();
        const minTimeBetweenWalkers = 2000; // 2 seconds
        
        if (now - lastWalkerTime < minTimeBetweenWalkers) {
            console.log('Skipping walker creation to prevent overlap');
            return;
        }
        
        // Create the walker element
        const walker = document.createElement('div');
        walker.className = 'character'; // The CSS already has the animation
        
        // Updated Priority order for GIFs:
        // 1. Special wallet received EXACTLY 0.00101 XRP (highest priority) - default_walker3.gif
        // 2. Special wallet received any other XRP amount (high priority) - happy.gif
        // 3. NFT mint transactions (lower priority) - default_walker1.gif
        // 4. Default walker (lowest priority) - default_walker.gif (via CSS)
        
        if (specialWalletExactAmount) {
            // Special wallet received EXACTLY 0.00101 XRP - HIGHEST priority
            console.log('Target wallet received EXACTLY 0.00101 XRP - using default_walker3.gif');
            walker.style.backgroundImage = "url('/static/images/default_walker3.gif')";
        } else if (specialWalletReceived) {
            // Special wallet received some XRP - high priority
            console.log('Target wallet received XRP payment - using happy.gif');
            walker.style.backgroundImage = "url('/static/images/happy.gif')";
        } else if (hasNFTMint) {
            // NFT mint transactions - medium priority
            console.log('Block contains NFT mint transactions - using default_walker1.gif');
            walker.style.backgroundImage = "url('/static/images/default_walker1.gif')";
        }
        // If none of the conditions match, use the default walker GIF (already set via CSS)
        
        // Calculate size based on transaction count
        const minSize = 100; // Minimum height (for blocks with very few txns)
        const maxSize = 400; // Maximum height (for blocks with many txns)
        
        // Dynamic scaling - higher txCount = larger character
        let walkerHeight = minSize + Math.min(txCount, 200) / 200 * (maxSize - minSize);
        let walkerWidth = walkerHeight; // Keep 1:1 aspect ratio
        
        // Apply the calculated size
        walker.style.width = walkerWidth + 'px';
        walker.style.height = walkerHeight + 'px';
        
        console.log(`Block with ${txCount} transactions → Character size: ${walkerHeight}px`);
        
        // Position characters on the same horizontal line
        const containerHeight = animationContainer.offsetHeight || 500;
        // Position the bottom of each character at the ground level
        const groundY = containerHeight - 20; // 20px from the bottom for some padding
        walker.style.top = (groundY - walkerHeight) + 'px';
        
        // Only create thinking cloud for default walker (not for special walkers)
        let thinkingCloud = null;
        
        // Display thinking cloud only for default walker (not for any special walkers)
        if (!hasNFTMint && !specialWalletReceived && !specialWalletExactAmount) {
            // Create the thinking cloud element - only for regular walkers
            thinkingCloud = document.createElement('div');
            thinkingCloud.className = 'thinking-cloud';
            
            // Size the cloud proportionally to the walker (but smaller)
            const cloudSize = walkerHeight * 0.9; // Cloud is 90% of walker size
            thinkingCloud.style.width = cloudSize + 'px';
            thinkingCloud.style.height = cloudSize + 'px';
            
            // Position the cloud above the right top corner of the walker
            // Use the same top position as walker but subtract cloud height + some offset
            const cloudTopOffset = 0; // Pixels above the walker
            const cloudRightOffset = 70; // Move 70px to the right
            
            const walkerTop = parseInt(walker.style.top);
            thinkingCloud.style.top = (walkerTop - cloudSize - cloudTopOffset) + 'px';
            
            // Add a left offset relative to the walker's animation
            thinkingCloud.style.marginLeft = cloudRightOffset + 'px';
        } else {
            // Log why we're not showing the thinking cloud
            if (specialWalletExactAmount) {
                console.log('Special amount walker detected - not displaying thinking cloud');
            } else if (specialWalletReceived) {
                console.log('Happy walker detected - not displaying thinking cloud');
            } else if (hasNFTMint) {
                console.log('NFT walker detected - not displaying thinking cloud');
            }
        }
        
        // The cloud will follow the same horizontal animation as the walker
        // We don't set left position as it's handled by the CSS animation
        
        // Update last walker time
        lastWalkerTime = now;
        
        // Add walker to container
        animationContainer.appendChild(walker);
        
        // Only add cloud if it exists (not for NFT walkers)
        if (thinkingCloud) {
            animationContainer.appendChild(thinkingCloud);
        }
        
        // Log event for debugging
        console.log(`Walker created: ${specialWalletExactAmount ? 'EXACT 0.00101 XRP' : 
                     specialWalletReceived ? 'XRP PAYMENT' : 
                     hasNFTMint ? 'NFT MINT' : 'REGULAR'} - 
                     size: ${walkerHeight}px, 
                     tx count: ${txCount}`);
                     
        // Also log to server for debugging
        if (specialWalletExactAmount || specialWalletReceived) {
            socket.emit('frontend_event', {
                type: 'special_wallet_detection',
                data: {
                    type: specialWalletExactAmount ? 'exact_amount' : 'any_amount',
                    timestamp: Date.now()
                }
            });
        }
        
        // Remove after animation (12 seconds)
        setTimeout(() => {
            if (walker.parentNode) {
                walker.parentNode.removeChild(walker);
            }
            if (thinkingCloud && thinkingCloud.parentNode) {
                thinkingCloud.parentNode.removeChild(thinkingCloud);
            }
            const message = thinkingCloud ? 'Removed completed walker and thinking cloud' : 'Removed completed NFT walker';
            console.log(message);
        }, 12000);
    }
    
    // Simple window resize handler
    window.addEventListener('resize', function() {
        console.log('Window resized');
    });
    
    // Add heartbeat to keep connection alive and detect silent failures
    setInterval(function() {
        if (socket.connected) {
            socket.emit('heartbeat', { timestamp: Date.now() });
            console.log('Heartbeat sent');
        } else {
            console.log('Cannot send heartbeat - socket disconnected');
            // Force reconnection attempt if needed
            socket.connect();
        }
    }, 30000); // 30 second heartbeat
});
