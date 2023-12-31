import json
import random
import time
from web3 import Web3, HTTPProvider, Account
import requests

# Reading configuration from a JSON file
with open("Json_data.JSON", 'r') as f:
    config = json.load(f)

# Reading private keys from a text file
with open('private_keys.txt', 'r') as keys_file:
    private_keys = keys_file.read().splitlines()

# Asking user if they want to send their entire balance
send_all_token = input("Do you want to send all balance? (y/n): ")
if send_all_token.lower() == "y":
    send_all_token = True
else:
    send_all_token = False
    # If not sending all balance, ask user for a range of amounts to send
    value_from = float(input("Enter the minimum amount to send: "))
    value_to = float(input("Enter the maximum amount to send: "))

# Asking the user for their desired gas price and delay between operations
desired_gas_price = int(input("Enter the desired gas price (the script will wait until the gas price is less than this number): "))
min_delay = int(input("Enter the minimum delay between operations: "))
max_delay = int(input("Enter the maximum delay between operations: "))

# RECOMMENDED SETTING
# send_all_token = True
# value_from = float(0.01)
# value_to = float(0.005)
# desired_gas_price = int(15)
# min_delay = int(200)
# max_delay = int(400)
# Importing necessary libraries

# Checking the Ethereum base fee and waiting until it decreases to the user's desired level
def wait_for_gas_price_to_decrease(node_url, desired_gas_price):
    """
    This function checks the current base fee of the Ethereum blockchain from a specific node
    and waits until it decreases to the desired level.

    :param node_url: URL of the Ethereum node.
    :param desired_gas_price: Desired base fee in Gwei.
    """
    while True:
        try:
            # Fetching the base fee for the latest block
            data = {
                "jsonrpc": "2.0",
                "method": "eth_getBlockByNumber",
                "params": ['latest', True],
                "id": 1
            }

            headers = {'Content-Type': 'application/json'}
            response = requests.post(node_url, headers=headers, data=json.dumps(data))
            response.raise_for_status()

            result = response.json()['result']
            current_base_fee = int(result['baseFeePerGas'], 16) / 10**9  # Convert from Wei to Gwei

        except requests.exceptions.HTTPError as errh:
            # Handle HTTP error and retry after 10 seconds
            print(f"HTTP Error: {errh}")
            time.sleep(10)
            continue
        except requests.exceptions.ConnectionError as errc:
            # Handle connection error and retry after 10 seconds
            print(f"Error Connecting: {errc}")
            time.sleep(10)
            continue

        # If the base fee is lower than the desired price, exit the loop
        if current_base_fee <= desired_gas_price:
            break

        print(f"Current base fee ({current_base_fee} Gwei) is higher than desired ({desired_gas_price} Gwei). Waiting...")
        time.sleep(10)


def bridge(config, private_key):
    # Initialize a connection to the Ethereum network.
    w3 = Web3(HTTPProvider(config['networks']['Ethereum']['url']))

    # Derive the account from the given private key.
    account = w3.eth.account.from_key(private_key)
    address_checksum = w3.to_checksum_address(account.address)

    # Define the contract details from the provided config.
    contract_name = "ZoraBridge"
    contract_details = config['contracts'][contract_name]
    contract_address = w3.to_checksum_address(contract_details['address'])
    contract = w3.eth.contract(address=contract_address, abi=contract_details['abi'])

    # Calculate the balance of the account and determine half of it.
    balance = w3.eth.get_balance(address_checksum)
    half_balance = balance // 2  # Using integer division for accuracy.

    # Fetch the current base fee from the Ethereum network.
    base_fee = w3.eth.fee_history(w3.eth.get_block_number(), 'latest')['baseFeePerGas'][-1]
    priority_max = w3.to_wei(1.5, 'gwei')

    # Build a fake transaction to estimate the gas required for the real transaction.
    fake_trx = contract.functions.depositTransaction(
        address_checksum, half_balance, 100000, False, b''
    ).build_transaction({
        'from': address_checksum,
        'value': half_balance,
        'nonce': w3.eth.get_transaction_count(account.address)
    })

    # Update the gas fees for the fake transaction.
    fake_trx.update({
        'maxFeePerGas': base_fee + priority_max,
        'maxPriorityFeePerGas': priority_max
    })

    # Estimate the gas required using the fake transaction.
    gas = w3.eth.estimate_gas(fake_trx)
    gas_cost = gas * (base_fee + priority_max)

    # If send_all_token is True, check if the balance can cover the gas costs.
    if send_all_token:
        balance = w3.eth.get_balance(address_checksum)
        if balance > gas_cost:
            value_wei = round(balance - 1.3 * gas_cost)
            value = w3.from_wei(value_wei, 'ether')
        else:
            print(f"Insufficient balance to cover gas costs. Balance: {balance}, Gas Cost: {gas_cost}")
            return 0
    else:
        value = random.uniform(value_from, value_to)
        value_wei = w3.to_wei(value, 'ether')

    # Build the real transaction for depositing funds.
    swap_txn = contract.functions.depositTransaction(
        address_checksum, value_wei, 100000, False, b''
    ).build_transaction({
        'from': address_checksum,
        'value': value_wei,
        'nonce': w3.eth.get_transaction_count(account.address)
    })

    # Update the gas fees and gas limit for the real transaction.
    swap_txn.update({
        'maxFeePerGas': base_fee + priority_max,
        'maxPriorityFeePerGas': priority_max,
        'gas': round(w3.eth.estimate_gas(swap_txn) * 1.15)
    })

    # Sign the transaction using the provided private key.
    signed_txn = w3.eth.account.sign_transaction(swap_txn, private_key)

    # Send the transaction to the Ethereum network and wait for a receipt.
    try:
        txn_hash = w3.eth.send_raw_transaction(signed_txn.rawTransaction)
        txn_receipt = w3.eth.wait_for_transaction_receipt(txn_hash, timeout=666)
    except (ValueError, Exception):  # Multiple exceptions can be caught using parentheses.
        print("Insufficient funds for transaction or other errors.")
        with open('failed_transactions.txt', 'a') as f:
            f.write(f'{address_checksum}, transaction failed due to error\n')
        return 0

    # Check the transaction status and log the result.
    if txn_receipt['status'] == 1:
        print(f"Transaction was successful, value = {value}")
        print(f"Wallet {address_checksum}")
        print(f"Txn hash: https://etherscan.io/tx/{txn_hash.hex()}")
        with open('successful_transactions.txt', 'a') as f:
            f.write(f'{address_checksum}, successful transaction, Txn hash: https://etherscan.io/tx/{txn_hash.hex()}\n')
        return 1
    else:
        print("Transaction was unsuccessful.")
        print(f"Wallet {address_checksum}")
        print(f"Txn hash: https://etherscan.io/tx/{txn_hash.hex()}")
        with open('failed_transactions.txt', 'a') as f:
            f.write(f'{address_checksum}, transaction failed, Txn hash: https://etherscan.io/tx/{txn_hash.hex()}\n')
        return 0

# Printing author's channel
print("Author channel: https://t.me/CryptoBub_ble")

# Shuffle private keys for randomness
random.shuffle(private_keys)

# Iterating through each private key, wait for the gas price to decrease, and then call the bridge function
for id, private_key in enumerate(private_keys):
    account = Account.from_key(private_key)
    wait_for_gas_price_to_decrease("https://ethereum.publicnode.com", desired_gas_price)
    print(f"Started work with wallet: {account.address}")
    try:
        bridge(config, private_key)
    except Exception as e:
        print("Error:", e)
        continue
    time.sleep(random.randint(min_delay, max_delay))
