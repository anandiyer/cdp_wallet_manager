#!/usr/bin/env python3
import sys
import json
import os
from pathlib import Path
from dotenv import load_dotenv
from cdp import Cdp, Wallet
import traceback
import time
from datetime import datetime, timedelta

class WalletManager:
    def __init__(self):
        self._load_credentials()
        self._load_env_config()
    
    def _load_credentials(self):
        """Load CDP API credentials from JSON file"""
        key_file = Path('cdp_api_key.json')
        if not key_file.exists():
            print("Error: cdp_api_key.json not found")
            print("Please ensure your CDP API credentials are in cdp_api_key.json")
            sys.exit(1)
        
        try:
            # Initialize CDP SDK with credentials from JSON file
            Cdp.configure_from_json(str(key_file.absolute()))
            Cdp.use_server_signer = True
            print("CDP SDK has been successfully configured from JSON file.")
            print("Server signer has been enabled for transaction signing.")
        except Exception as e:
            print(f"Error configuring CDP SDK: {str(e)}")
            print(traceback.format_exc())
            sys.exit(1)
    
    def _load_env_config(self):
        """Load configuration from .env file"""
        env_path = Path('.') / '.env'
        if not env_path.exists():
            self._create_default_env_file()
            print("Warning: .env file not found. A template has been created.")
            print("Using default values for network and storage path.")
        
        load_dotenv()
        
        # Load configuration with defaults
        self.network = os.getenv('NETWORK', 'base-sepolia')
        self.wallet_path = Path(os.getenv('WALLET_STORAGE_PATH', './wallets'))
        
        # Ensure wallet directory exists
        self.wallet_path.mkdir(exist_ok=True)
    
    def _create_default_env_file(self):
        """Creates a default .env file template"""
        default_env_content = """# Network Configuration
NETWORK=base-sepolia  # Options: base-sepolia, base-mainnet, etc.

# Storage Configuration
WALLET_STORAGE_PATH=./wallets  # Directory for storing wallet files
"""
        with open('.env', 'w') as f:
            f.write(default_env_content)

    def _wait_for_transfer(self, transfer, timeout_minutes=10) -> bool:
        """
        Wait for transfer to complete.
        Returns True if successful, False if failed.
        """
        start_time = datetime.now()
        timeout = start_time + timedelta(minutes=timeout_minutes)
        
        # Debug: Print all available attributes of transfer
        print("\nTransfer object details:")
        print(f"All attributes: {dir(transfer)}")
        print(f"Status value: {transfer.status}")
        print(f"Status type: {type(transfer.status)}")
        print(f"Status class module: {transfer.status.__class__.__module__}")
        print(f"Status possible values: {list(type(transfer.status).__members__.keys()) if hasattr(type(transfer.status), '__members__') else 'Not available'}")
        
        while datetime.now() < timeout:
            # Refresh the transfer status
            transfer.reload()
            current_status = transfer.status
            print(f"\nCurrent status: {current_status}")
            
            # Compare status values by string representation
            status_str = str(current_status).lower()
            
            if 'complete' in status_str:
                print("Transfer completed!")
                return True
            elif 'failed' in status_str:
                print("Transfer failed!")
                return False
            elif 'pending' in status_str:
                print(".", end='', flush=True)
                time.sleep(2)
                continue
            else:
                print(f"Unexpected status: {current_status}")
                return False
        
        print(f"\nTransfer timed out after {timeout_minutes} minutes!")
        return False

    def list_wallets(self) -> None:
        """Lists all available wallets"""
        try:
            print("\nFetching wallets...")
            wallets = list(Wallet.list())
            print(f"Found {len(wallets)} wallet(s):")
            
            for wallet in wallets:
                print(f"\nWallet ID: {wallet.id}")
                print(f"Address: {wallet.default_address.address_id}")
                print(f"Network: {wallet.network_id}")
                print(f"Can Sign: {wallet.can_sign}")
                print(f"Server Signer Status: {wallet.server_signer_status}")
                
                # Show balances for each wallet
                wallet.reload()  # Refresh state
                balances = wallet.balances()
                if balances:
                    print("Balances:")
                    for asset_id, balance in balances.items():
                        print(f"  {asset_id.upper()}: {balance}")
                else:
                    print("No balances found")
                print("-" * 50)

        except Exception as e:
            print(f"Error listing wallets: {str(e)}")
            print(traceback.format_exc())

    def create_wallet(self) -> None:
        """Creates a new wallet and saves its data for recovery"""
        try:
            # Create new wallet
            wallet = Wallet.create(self.network)
            
            # Get the wallet's address
            address = wallet.default_address
            
            # Store wallet data
            wallet_data = {
                "address": address.address_id,
                "network": self.network,
                "wallet_id": wallet.id
            }
            
            # Save to file
            filename = self.wallet_path / f"{address.address_id}.txt"
            with open(filename, 'w') as f:
                json.dump(wallet_data, f, indent=4)
            
            print(f"\nNew wallet created successfully!")
            print(f"Wallet ID: {wallet.id}")
            print(f"Address: {address.address_id}")
            print(f"Network: {self.network}")
            print(f"Can Sign: {wallet.can_sign}")
            print(f"Server Signer Status: {wallet.server_signer_status}")
            print(f"Wallet info saved to: {filename}")
            
            # Fund wallet if on testnet
            if self.network == 'base-sepolia':
                print("\nAttempting to fund wallet with testnet ETH...")
                try:
                    faucet_tx = wallet.faucet()
                    faucet_tx.wait()
                    print("Wallet funded successfully with testnet ETH")
                    print("\nInitial balance:")
                    balances = wallet.balances()
                    for asset_id, balance in balances.items():
                        print(f"{asset_id.upper()}: {balance}")
                except Exception as e:
                    print(f"Note: Faucet funding failed: {str(e)}")
            
        except Exception as e:
            print(f"Error creating wallet: {str(e)}")
            print(traceback.format_exc())
            sys.exit(1)

    def show_balance(self, wallet_address: str) -> None:
        """Shows token balances and transfer history"""
        try:
            wallet_file = self.wallet_path / f"{wallet_address}.txt"
            try:
                with open(wallet_file, 'r') as f:
                    wallet_info = json.load(f)
            except FileNotFoundError:
                print(f"Error: Wallet file not found at {wallet_file}")
                return

            # Find the wallet in the list of wallets
            wallets = list(Wallet.list())
            target_wallet = None
            for wallet in wallets:
                if wallet.default_address.address_id == wallet_address:
                    target_wallet = wallet
                    break
            
            if not target_wallet:
                print(f"Error: Wallet {wallet_address} not found in CDP")
                return
                
            # Refresh wallet state
            target_wallet.reload()
            
            print(f"\nWallet Information:")
            print(f"Wallet ID: {target_wallet.id}")
            print(f"Address: {wallet_address}")
            print(f"Network: {wallet_info['network']}")
            print(f"Can Sign: {target_wallet.can_sign}")
            print(f"Server Signer Status: {target_wallet.server_signer_status}")
            
            # Show current balances
            print("\nCurrent balances:")
            balances = target_wallet.balances()
            if balances:
                for asset_id, balance in balances.items():
                    print(f"{asset_id.upper()}: {balance}")
            else:
                print("No balances found")
            
            # Show transfer history
            print("\nTransfer history:")
            transfers = list(target_wallet.default_address.transfers())
            if transfers:
                for transfer in transfers:
                    print(f"Transfer: {transfer}")
            else:
                print("No transfer history found")

        except Exception as e:
            print(f"Error showing balance: {str(e)}")
            print(traceback.format_exc())

    def send_tokens(self, from_address: str, to_address: str, quantity: float, asset_id: str) -> None:
        """Sends tokens from one address to another"""
        try:
            # Load wallet data
            wallet_file = self.wallet_path / f"{from_address}.txt"
            try:
                with open(wallet_file, 'r') as f:
                    wallet_info = json.load(f)
            except FileNotFoundError:
                print(f"Error: Wallet file not found at {wallet_file}")
                return

            print(f"\nLocating wallet {from_address}...")
            
            # Find the wallet in the list of wallets
            wallets = list(Wallet.list())
            target_wallet = None
            for wallet in wallets:
                if wallet.default_address.address_id == from_address:
                    target_wallet = wallet
                    break
            
            if not target_wallet:
                print(f"Error: Wallet {from_address} not found in CDP")
                return
                
            # Refresh wallet state
            target_wallet.reload()
            
            print(f"Wallet signing capability: {target_wallet.can_sign}")
            print(f"Server signer status: {target_wallet.server_signer_status}")
            
            print("\nChecking current balance...")
            try:
                balances = target_wallet.balances()
                print("\nCurrent balance:")
                for aid, balance in balances.items():
                    print(f"{aid.upper()}: {balance}")

                # Verify sufficient balance
                asset_id = asset_id.lower()
                current_balance = float(balances.get(asset_id, 0))
                if current_balance < quantity:
                    print(f"\nError: Insufficient balance")
                    print(f"Required: {quantity} {asset_id.upper()}")
                    print(f"Available: {current_balance} {asset_id.upper()}")
                    return
            except Exception as e:
                print(f"Error checking balance: {str(e)}")
                print(traceback.format_exc())
                return

            # Print transaction details
            print("\nTransaction Details:")
            print(f"From: {from_address}")
            print(f"To: {to_address}")
            print(f"Amount: {quantity}")
            print(f"Asset ID: {asset_id}")
            print(f"Network: {wallet_info['network']}")
            print(f"Gasless: {asset_id == 'usdc'}")
            
            # Get user confirmation
            confirm = input("\nProceed with transaction? (yes/no): ").lower()
            if confirm != 'yes':
                print("Transaction cancelled")
                return

            # Send transfer
            print("\nPreparing transaction...")
            gasless = asset_id == 'usdc'
            
            print("Creating transfer...")
            transfer = target_wallet.transfer(
                amount=quantity,
                asset_id=asset_id,
                destination=to_address,
                gasless=gasless
            )
            
            # Print initial transfer info
            print(f"Transfer created with status: {transfer.status}")
            
            if self._wait_for_transfer(transfer):
                print("\nTransfer completed successfully!")
                if hasattr(transfer, 'transaction_hash'):
                    print(f"Transaction hash: {transfer.transaction_hash}")
                if hasattr(transfer, 'getTransactionLink'):
                    print(f"Transaction link: {transfer.getTransactionLink()}")
                
                # Refresh and show updated balance
                target_wallet.reload()
                print("\nUpdated balance:")
                balances = target_wallet.balances()
                for aid, balance in balances.items():
                    print(f"{aid.upper()}: {balance}")
            else:
                print("\nTransfer failed or timed out!")
                if hasattr(transfer, 'error'):
                    print(f"Error details: {transfer.error}")

        except Exception as e:
            print(f"Error sending tokens: {str(e)}")
            print(traceback.format_exc())

def print_usage():
    """Prints usage instructions"""
    print("""
Usage:
    create-wallet
    list-wallets
    send <from-wallet-address> <to-wallet-address> <quantity> <asset-id>
    show-balance <wallet-address>

Example commands:
    python3 wallet_manager.py create-wallet
    python3 wallet_manager.py list-wallets
    python3 wallet_manager.py send 0x123... 0x456... 0.0001 eth
    python3 wallet_manager.py show-balance 0x123...

Note: 
- Ensure cdp_api_key.json exists with your CDP API credentials
- Configuration can be customized in .env file:
  - NETWORK: The blockchain network to use
  - WALLET_STORAGE_PATH: Directory for wallet files
- Asset ID examples: 'eth', 'usdc' (USDC transfers are gasless)
- New wallets on base-sepolia will be auto-funded with testnet ETH
    """)

def main():
    if len(sys.argv) < 2:
        print_usage()
        return
    
    manager = WalletManager()
    command = sys.argv[1].lower()
    
    if command == 'create-wallet':
        manager.create_wallet()
    
    elif command == 'list-wallets':
        manager.list_wallets()
    
    elif command == 'send' and len(sys.argv) == 6:
        from_address = sys.argv[2]
        to_address = sys.argv[3]
        quantity = float(sys.argv[4])
        asset_id = sys.argv[5]
        manager.send_tokens(from_address, to_address, quantity, asset_id)
    
    elif command == 'show-balance' and len(sys.argv) == 3:
        wallet_address = sys.argv[2]
        manager.show_balance(wallet_address)
    
    else:
        print_usage()

if __name__ == "__main__":
    main()
