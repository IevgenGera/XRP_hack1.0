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
        
        // 1b. Check if specific wallet received EXACTLY 0.0011 XRP (cat animation)
        const specialWalletCatAmount = checkSpecificWalletReceivedCatAmount(data);
        
        // 2. Check if specific wallet received any XRP (high priority)
        const specialWalletReceived = checkSpecificWalletReceivedXRP(data);
        
        // 3. Check if there are any NFT mint transactions (medium priority)
        const hasNFTMint = checkForNFTMintTransactions(data);
        
        // EXTREME APPROACH: Complete override of memo system to guarantee prioritization
        let selectedMemos = [];

        // Entirely new approach to memo selection
        // Only allow special wallet memos when present
        // CRITICAL: Check each condition explicitly and individually
        
        // Check for special wallet memos first - this is our ONLY priority
        if (data && data.tx_details) {
            // Check explicitly if special wallet received payment
            const specialWalletReceivedPayment = data.tx_details.special_wallet_received_xrp === true;
            
            // Check explicitly for the memos flag
            const hasSpecialWalletMemoFlag = data.tx_details.has_special_wallet_memo === true;
            
            // Check directly if special wallet memos array exists and has content
            const specialWalletMemosExist = Array.isArray(data.tx_details.special_wallet_memos) && 
                                           data.tx_details.special_wallet_memos.length > 0;
            
            console.log('Special wallet payment?', specialWalletReceivedPayment);
            console.log('Has memo flag?', hasSpecialWalletMemoFlag);
            console.log('Special wallet memos exist?', specialWalletMemosExist);
            
            // CRITICAL SPECIAL WALLET MEMO CHECK
            if (specialWalletReceivedPayment && hasSpecialWalletMemoFlag && specialWalletMemosExist) {
                console.log('🔴 HIGHEST PRIORITY: Special wallet payment with memo detected!');
                
                // Take ONLY the first special wallet memo
                const firstMemo = data.tx_details.special_wallet_memos[0];
                
                // Add one more validation on the memo data
                if (firstMemo && typeof firstMemo.memo_data === 'string' && firstMemo.memo_data.trim() !== '') {
                    console.log('🔴 CRITICAL: Using ONLY this special wallet memo:', firstMemo.memo_data);
                    
                    // Use ONLY this one memo
                    selectedMemos = [firstMemo];
                }
            }
            // If we don't have a special wallet memo, then we can try regular memos as fallback
            else if (!specialWalletReceivedPayment && 
                     Array.isArray(data.tx_details.transaction_memos) && 
                     data.tx_details.transaction_memos.length > 0) {
                     
                console.log('No special wallet payment detected, using regular memo as fallback');
                selectedMemos = data.tx_details.transaction_memos;
            }
        }
        
        if (selectedMemos.length > 0) {
            console.log(`FINAL DECISION: Using ${selectedMemos.length} memos for display:`, selectedMemos);
        } else {
            console.log('No valid memos found for display');
        }
        
        // Update payment tracker if special wallet received payments
        if (specialWalletExactAmount || specialWalletCatAmount) {
            updatePaymentTracker(true); // Exact amount
        } else if (specialWalletReceived) {
            updatePaymentTracker(false); // Any amount
        }
        
        // Create a walker with appropriate attributes
        const txCount = data.txn_count || 0;
        createWalker(txCount, hasNFTMint, specialWalletReceived, specialWalletExactAmount, specialWalletCatAmount, selectedMemos);
    });
    
    // Function to check if specific wallet received EXACTLY 0.00101 XRP
    function checkSpecificWalletReceivedExactAmount(blockData) {
        if (blockData && blockData.tx_details && blockData.tx_details.special_wallet_received_exact_amount === true) {
            console.log('Backend detected special wallet received EXACTLY 0.00101 XRP in this block!');
            return true;
        }
        return false;
    }
    
    // Function to check if specific wallet received EXACTLY 0.0011 XRP (cat animation)
    function checkSpecificWalletReceivedCatAmount(blockData) {
        if (blockData && blockData.tx_details && blockData.tx_details.special_wallet_received_cat_amount === true) {
            console.log('Backend detected special wallet received EXACTLY 0.0011 XRP in this block - cat animation!');
            return true;
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
    
    // THIS FUNCTION IS REMOVED - We're using direct selection in the socket.on handler
    // for more reliable memo extraction. This function is kept as a reference but not used.
    function extractMemos_DEPRECATED(blockData) {
        console.log('WARNING: This function is deprecated and should not be called');
        return [];
    }
    
    // Function to create a walker div with size based on transaction count
    function createWalker(txCount = 100, hasNFTMint = false, specialWalletReceived = false, specialWalletExactAmount = false, specialWalletCatAmount = false, memos = []) { // Default to 100 txns if not specified
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
        // 1. Special wallet received EXACTLY 0.0011 XRP (highest priority) - spinning_cat.gif
        // 2. Special wallet received EXACTLY 0.00101 XRP (second highest priority) - default_walker3.gif
        // 3. Special wallet received any other XRP amount (high priority) - happy.gif
        // 4. NFT mint transactions (lower priority) - default_walker1.gif
        // 5. Default walker (lowest priority) - default_walker.gif (via CSS)
        
        if (specialWalletCatAmount) {
            // Special wallet received EXACTLY 0.0011 XRP - HIGHEST priority (cat animation)
            console.log('Target wallet received EXACTLY 0.0011 XRP - using spinning_cat.gif');
            walker.style.backgroundImage = "url('/static/images/spinning_cat.gif')";
        } else if (specialWalletExactAmount) {
            // Special wallet received EXACTLY 0.00101 XRP - SECOND highest priority
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
        
        // Thinking cloud is turned off as requested
        let thinkingCloud = null;
        
        // No thinking cloud will be created
        
        // Update last walker time
        lastWalkerTime = now;
        
        // Add walker to container
        animationContainer.appendChild(walker);
        
        // Thinking cloud is completely disabled
        
        // Add memo bubble if there are memos - EXTREME validation
        if (memos && Array.isArray(memos) && memos.length > 0) {
            // Use ONLY the first memo
            const memo = memos[0];
            console.log('🔄 Processing memo for display:', memo);
            
            // Triple check the memo structure and content
            if (!memo || typeof memo !== 'object') {
                console.error('❌ Invalid memo object:', memo);
                return; // Stop processing if memo is invalid
            }
            
            // Extract content with explicit validation
            let memoContent = '';
            if (memo.memo_data && typeof memo.memo_data === 'string' && memo.memo_data.trim() !== '') {
                memoContent = memo.memo_data;
                console.log('✅ Valid memo content found:', memoContent);
            } else {
                console.error('❌ Invalid or empty memo_data');
                return; // Stop processing if memo content is invalid
            }
            
            // Only create bubble if we have content
            if (memoContent && memoContent.trim() !== '') {
                console.log('Creating memo bubble with content:', memoContent);
                
                // Create the memo bubble
                const memoBubble = document.createElement('div');
                memoBubble.className = 'memo-bubble';
                memoBubble.textContent = memoContent;
                
                // Position the bubble centered above the walker
                const walkerTop = parseInt(walker.style.top);
                const bubbleHeight = 60; // Adjusted for new bigger bubble
                const bubbleOffset = 40; // Space between bubble and walker
                
                // Create a fixed position for the bubble that stays with the walker
                memoBubble.style.position = 'absolute';
                memoBubble.style.top = (walkerTop - bubbleHeight - bubbleOffset) + 'px';
                
                // Position the bubble so its 25% point is aligned with the walker's center
                // This aligns the speech bubble's pointer with the walker
                memoBubble.style.left = '25%';
                
                // Apply a specific offset to ensure walker is under the pointer
                const walkerWidth = parseInt(walker.style.width);
                const offsetAdjustment = walkerWidth / 4; // Quarter of walker width
                memoBubble.style.marginLeft = offsetAdjustment + 'px';
                
                // Make the bubble track with the walker
                memoBubble.style.animation = 'moveAcross 10s linear forwards, floatBubble 2s ease-in-out infinite';
                
                // Add the memo bubble to the container
                animationContainer.appendChild(memoBubble);
                
                // Remove the bubble along with the walker
                setTimeout(() => {
                    if (memoBubble.parentNode) {
                        memoBubble.parentNode.removeChild(memoBubble);
                    }
                }, 12000);
                
                console.log(`Added memo bubble with text: ${memo.memo_data}`);
            }
        }
        
        // Log event for debugging
        console.log(`Walker created: ${specialWalletCatAmount ? 'EXACT 0.0011 XRP' : 
                     specialWalletExactAmount ? 'EXACT 0.00101 XRP' : 
                     specialWalletReceived ? 'XRP PAYMENT' : 
                     hasNFTMint ? 'NFT MINT' : 'REGULAR'} - 
                     size: ${walkerHeight}px, 
                     tx count: ${txCount}`);
                     
        // Also log to server for debugging
        if (specialWalletCatAmount || specialWalletExactAmount || specialWalletReceived) {
            socket.emit('frontend_event', {
                type: 'special_wallet_detection',
                data: {
                    type: specialWalletCatAmount ? 'cat_amount' : 
                          specialWalletExactAmount ? 'exact_amount' : 'any_amount',
                    timestamp: Date.now()
                }
            });
        }
        
        // Remove walker and cloud after animation (12 seconds)
        setTimeout(() => {
            if (walker.parentNode) {
                walker.parentNode.removeChild(walker);
            }
            if (thinkingCloud && thinkingCloud.parentNode) {
                thinkingCloud.parentNode.removeChild(thinkingCloud);
            }
            const message = 'Removed completed walker';
            console.log(message);
        }, 12000);
    }
    
    // Simple window resize handler
    window.addEventListener('resize', function() {
        console.log('Window resized');
    });
    
    // Collapse button handler
    const collapseBtn = document.getElementById('collapse-btn');
    const infoPanel = document.getElementById('info-panel');
    
    // Enhanced collapse button function
    collapseBtn.addEventListener('click', function(e) {
        // Prevent any default action
        e.preventDefault();
        
        // Toggle the collapsed class
        infoPanel.classList.toggle('collapsed');
        
        // Set aria-expanded attribute for accessibility
        const isCollapsed = infoPanel.classList.contains('collapsed');
        collapseBtn.setAttribute('aria-expanded', !isCollapsed);
        
        console.log('Panel collapse toggled, collapsed state:', isCollapsed);
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
