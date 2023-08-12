import requests
import json
import re
import platform
import os
import argparse
import subprocess
import pty

# Set up argparse
parser = argparse.ArgumentParser(description="Generate Python code based on a user request.")
parser.add_argument('--debug', action='store_true', help="Enable debugging output.")
args = parser.parse_args()
DEBUG = args.debug
REQUEST_COUNT = 0

# Debug print function
def debug_print(*args, **kwargs):
    if DEBUG:
        print(*args, **kwargs)

# Configuration
try:
    with open('apikey.txt', 'r') as api_key_file:
        OPENAI_API_KEY = api_key_file.read().strip()
except FileNotFoundError:
    print("api_key.txt not found. Ensure you have your OpenAI API key in that file.")
    exit(1)

API_ENDPOINT = 'https://api.openai.com/v1/chat/completions'
STARTING_PROMPT = '''Request: I'm working on a Kali-Linux-Headless in WSL and need a Python script named temp_code_to_execute.py. Specifically, I'd like the script to '''
USER_REQUEST = input("Create a python script that can: ")

def clear_screen():
    system_name = platform.system()
    
    if system_name == "Windows":
        os.system("cls")
    else:
        os.system("clear")

def print_request_count():
    """Print the total number of requests made to OpenAI."""
    print(f"Total Requests made to OpenAI: {REQUEST_COUNT}") 
       
def send_request_to_openai(messages, max_tokens=2000):
    global REQUEST_COUNT  # Declare the variable as global so that we can modify it
    
    headers = {'Authorization': f'Bearer {OPENAI_API_KEY}', 'Content-Type': 'application/json'}
    request_body = {"model": "gpt-3.5-turbo", "messages": messages, "max_tokens": max_tokens}
    response = requests.post(API_ENDPOINT, headers=headers, data=json.dumps(request_body))
    
    # Increment the counter each time a request is made
    REQUEST_COUNT += 1

    return response.json().get('choices', [{}])[0].get('message', {}).get('content', '') if response.status_code == 200 else ''

def extract_code_blocks(text, mode="install"):
    code_blocks_double = re.findall(r'```(.*?)(?:\n)(.*?)```', text, re.DOTALL)
    code_blocks_single = re.findall(r'`(.*?)`', text)

    # Extract only the code from the double backtick blocks
    blocks = [block[1] for block in code_blocks_double] + code_blocks_single

    # If extracting install commands, look for pip or apt-get commands
    if mode == "install":
        install_blocks = [block for block in blocks if "pip" in block or "apt-get" in block]
        return install_blocks

    # Filter out non-Python code blocks
    python_blocks = []
    for block in blocks:
        if any(keyword in block for keyword in ["import", "def", "class", "print"]):
            python_blocks.append(block)

    # If there are multiple code blocks, keep the largest one (as it is most likely the actual code)
    if python_blocks:
        largest_block = max(python_blocks, key=len)
        return [largest_block]
    else:
        return []

def gameplan_and_code_request():
    messages = [
        {"role": "system", "content": "Do not add any code snippets or actual code to this request just write a gameplan on how to achieve it"},
        {"role": "user", "content": STARTING_PROMPT + USER_REQUEST}
    ]
    gameplan = send_request_to_openai(messages)
    debug_print("Game Plan:", gameplan)  # Debug print game plan

    messages = [
        {"role": "system", "content": "Based on this, please provide me the pip or apt-get commands for things I need to make sure are installed."},
        {"role": "user", "content": gameplan}
    ]
    install_commands = send_request_to_openai(messages)
    installs = extract_code_blocks(install_commands, mode="install")
    debug_print("Install Commands:", install_commands)  # Debug print installation commands

    # Clean Install Commands
    clean_installs = '\n'.join(installs)
    debug_print("Install Commands:\n", clean_installs)  # Debug print cleaned installation commands

    # Fetch Final Code
    retrieve_code_msg = f"Based on our gameplan: {gameplan}, provide the python code as per my request."
    messages = [
        {"role": "system", "content": "Now, provide the actual Python code based on the game plan. The code should be enclosed in a single markdown code block."},
        {"role": "user", "content": retrieve_code_msg}
    ]
    final_code = send_request_to_openai(messages)
    
    # Clean Code Response
    code_blocks = extract_code_blocks(final_code, mode="code")
    clean_code = '\n'.join(code_blocks) if code_blocks else "No code received."
    
    debug_print("\nFinal Code:\n", clean_code)  # Debug print cleaned code response
    
    return installs, clean_code

def save_and_execute_python_code(code, ask_for_confirmation):
    """Save the python code block to a file and execute it."""
    with open('temp_code_to_execute.py', 'w') as f:
        f.write(code)

    while True:
        if ask_for_confirmation:
            choice = input("Execute the code now? (yes/no): ").strip().lower()
        else:
            choice = 'yes'  # Skip the choice and execute directly

        if choice == 'yes':
            try:
                stdout, stderr = run_python_file_with_pty("temp_code_to_execute.py")
                
                execution_error = None
                
                # Check if the output contains the word "Error"
                if "Error:" in stdout or "Error:" in stderr or "Traceback" in stdout:
                    execution_error = "An error occurred during execution."
                
                # If there's an error, ask the user if they'd like to send the traceback and code for a fix
                if execution_error:
                    print("It seems the code encountered a Traceback error when trying to execute")
                    send_for_fix = input("Do you want to send the traceback and the code to find a fix? (yes/no): ").strip().lower()
                    if send_for_fix == 'yes':
                        # Send to OpenAI for suggestions
                        feedback_message = f"Here's the code that caused an error:\n```{code}```\nError message: {execution_error}\n\nHow can I fix this error?"
                        messages = [
                            {"role": "system", "content": "The user has encountered an error with this code. Please provide a fix or suggestion:"},
                            {"role": "user", "content": feedback_message}
                        ]
                        fix_suggestion = send_request_to_openai(messages)
                        new_installs = extract_code_blocks(fix_suggestion, mode="install")

                        # Clean Code Response
                        code_blocks = extract_code_blocks(fix_suggestion, mode="code")
                        fix_suggestion = '\n'.join(code_blocks) if code_blocks else "No code received."

                        # Extract new install commands from the fix_suggestion
                        install_commands, code = gameplan_and_code_request()

                        # Deduplicate the list of installation commands
                        updated_install_commands = list(set(install_commands))                        
                        
                        if updated_install_commands:
                            print("\nTo Install:\n")
                            print(f"{updated_install_commands}")
                            for updated_command_to_install in updated_install_commands:
                                while True:
                                    if ask_for_confirmation:
                                        print(updated_command_to_install)
                                        choice = input("Execute the install command now? (yes/no): ").strip().lower()
                                    else:
                                        choice = 'yes'  # Skip the choice and execute directly      

                                    if choice == 'yes':
                                        try:
                                            subprocess.run(updated_command_to_install, shell=True, check=True)
                                            print(f"Installation successful: {updated_command_to_install}")
                                        except subprocess.CalledProcessError as e:
                                            print(f"Installation failed: {updated_command_to_install}")
                                            print(f"Error message: {e}")
                                            # Send a request to get new commands to install/new approach to the code
                                        break
                                    elif choice == 'no':
                                        return
                                    else:
                                        print("Invalid choice. Please enter 'yes' or 'no'. Try again.")
                        if fix_suggestion:
                            working_output_check(fix_suggestion, ask_for_confirmation)
                            
                return stdout, stderr, execution_error
                
            except Exception as e:
                execution_error = str(e)
                return "", "", execution_error
        elif choice == 'no':
            return None
        else:
            print("Invalid choice. Please enter 'yes' or 'no'. Try again.")


def run_python_file_with_pty(file_path):
    master, slave = pty.openpty()

    process = subprocess.Popen(['python', file_path], stdout=slave, stderr=slave, close_fds=True)
    os.close(slave)

    stdout = []
    stderr = []  # Note: In our current setup, stderr will be empty as we're not distinguishing between stdout and stderr.
    while True:
        try:
            data = os.read(master, 512).decode()
            if not data:
                break
            stdout.append(data)
        except OSError:
            break

    return ''.join(stdout), ''.join(stderr)  # For now, stderr is empty

def working_output_check(initial_code, ask_for_confirmation):
    code = initial_code
    print("initial code: {initial_code}")
    while True:  
        stdout, stderr, execution_error = save_and_execute_python_code(code, ask_for_confirmation)
        
        if stdout:
            print("Standard Output From Code Execution:")
            print("=" * 50)
            print(f"\n{stdout}")
            print("=" * 50)

        if stderr:
            debug_print("Standard Error From Code Execution:")
            debug_print("=" * 50)
            debug_print(stderr)
            debug_print("=" * 50)

        if execution_error:
            debug_print("Execution Error From Code Execution:")
            debug_print("=" * 50)
            debug_print(execution_error)
            debug_print("=" * 50)

        choice = input("Are you happy with the code output? (yes/no): ").strip().lower()

        if choice == 'yes':
            print("Output can be reproduced by running the temp_code_to_execute.py file anytime.")
            break
        elif choice == 'no':
            retrieve_feedback = input("Please provide your feedback on what to change: ")

            # Include the code and the execution error in the feedback sent to OpenAI
            code_feedback = f"My code executed as follows:\n```{code}```\nExecution Error: {execution_error}\n\nI would like to make these changes: {retrieve_feedback}\n\nPlease provide the full updated code"

            messages = [
                {"role": "system", "content": "Here is my code, I would like to make these changes, Please provide the full updated code:"},
                {"role": "user", "content": code_feedback}
            ]
            
            while True: 
                make_changes_to_code = send_request_to_openai(messages)
                
                if make_changes_to_code:
                    code_blocks = extract_code_blocks(make_changes_to_code, mode="code")
                    if code_blocks:  
                        code = '\n'.join(code_blocks)
                        print("\nUpdated Code:\n")  # Display the updated code to the user
                        print("=" * 50)
                        print(f"\n{code}")
                        print("=" * 50)
                        break
                    else:
                        print("The response from OpenAI did not contain valid code. Retrying...")
                else:
                    print("Failed to get a response from OpenAI. Retrying...")
        else:
            print("Invalid choice. Please enter 'yes' or 'no'. Try again.")
                    
def generate_output(ask_for_confirmation):        
    install_commands, code = gameplan_and_code_request()

    # Deduplicate the list of installation commands
    install_commands = list(set(install_commands))

    # Execute the installation commands first
    if install_commands:
        print("\nTo Install:\n")
        debug_print(f"{install_commands}")
        for command_to_install in install_commands:
            while True:
                if ask_for_confirmation:
                    print(command_to_install)
                    choice = input("Execute the install command now? (yes/no): ").strip().lower()
                else:
                    choice = 'yes'  # Skip the choice and execute directly      

                if choice == 'yes':
                    try:
                        subprocess.run(command_to_install, shell=True, check=True)
                        print(f"Installation successful: {command_to_install}")
                    except subprocess.CalledProcessError as e:
                        print(f"Installation failed: {command_to_install}")
                        print(f"Error message: {e}")
                        # Send a request to get new commands to install/new approach to the code
                    break
                elif choice == 'no':
                    print("Continuing without installing the recommending requirement.")
                    break
                else:
                    print("Invalid choice. Please enter 'yes' or 'no'. Try again.")

        
    # Then execute the actual python code
    if code:
        print("\nTo Execute:\n")
        print("=" * 50)
        print(f"\n{code}")
        print("=" * 50)

    print_request_count()

    working_output_check(code, ask_for_confirmation)

generate_output(ask_for_confirmation=True)
