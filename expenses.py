import json
import pandas as pd
from datetime import datetime
import os
import telebot
from collections import defaultdict
from telebot import types  # For creating buttons
from apscheduler.schedulers.background import BackgroundScheduler  # Scheduler
import matplotlib.pyplot as plt  # For chart creation

# Initialize Telegram bot (replace with your bot token)
TOKEN = '7217939481:AAG72aIGrvIviBDvviVdkMyIGELGZx7Dv5k'
bot = telebot.TeleBot(TOKEN)

# Path for saving JSON and Excel files
json_file = 'expenses.json'
excel_file = 'expenses.xlsx'

# Your Telegram chat ID to send the report
YOUR_CHAT_ID = '1516755631'

# Load JSON data safely
def load_json_data(json_file):
    if os.path.exists(json_file):
        try:
            with open(json_file, 'r') as f:
                return json.load(f)
        except json.JSONDecodeError:
            return defaultdict(list)  # Return empty if JSON is invalid
    else:
        return defaultdict(list)

# Load existing data from JSON
data = load_json_data(json_file)

# Dictionary to store user information based on chat ID
user_data = {}

# Predefined categories
categories = ['food', 'delivery', 'sport', 'cloths', 'laundry', 'documents', 'else']

# Helper function to normalize user names
def normalize_username(username):
    return username.capitalize()

# Function to add expense and merge if same category for the same day
def add_or_merge_expense(chat_id, category, amount):
    user = user_data[chat_id]['username']
    today = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    found = False

    # Check if an entry already exists for the same category today
    for entry in data[user]:
        if entry['date'][:10] == today[:10] and entry['category'] == category:
            entry['amount'] += amount
            found = True
            break

    if not found:
        # Create a new entry if not found
        entry = {'date': today, 'category': category, 'amount': amount}
        data[user].append(entry)

    # Save to JSON
    with open(json_file, 'w') as f:
        json.dump(data, f, indent=4)

    # Convert to DataFrame and append to Excel
    df = pd.DataFrame([{**entry, 'user': user}])

    if not os.path.exists(excel_file):
        df.to_excel(excel_file, index=False, engine='openpyxl')
    else:
        existing_df = pd.read_excel(excel_file)
        new_df = pd.concat([existing_df, df], ignore_index=True)
        new_df.to_excel(excel_file, index=False, engine='openpyxl')

# Greeting message when user starts the bot
@bot.message_handler(commands=['start'])
def send_welcome(message):
    chat_id = message.chat.id
    if chat_id not in user_data:
        user_data[chat_id] = {'username': None}

    welcome_text = ("Welcome to the Expense Tracker Bot! 🤑\n"
                    "This bot helps you track your daily expenses. "
                    "You can use the /add command to add expenses. "
                    "Use /week_total and /month_total to view your own expense summary for the week or month. "
                    "Every Monday at 00:00 AM, the bot will send the weekly summary to all users, and "
                    "on the 1st day of each month, the bot will send the monthly summary.")

    # Send greeting message and ask for username
    msg = bot.send_message(chat_id, welcome_text)
    bot.register_next_step_handler(msg, ask_for_username)

# Step 1: Ask for username if not already provided
def ask_for_username(message):
    chat_id = message.chat.id
    username = normalize_username(message.text)
    user_data[chat_id]['username'] = username
    bot.send_message(chat_id, f"Username set to {username}. You can now add expenses using the /add command.")

# Step 2: /add command to start the expense entry process
@bot.message_handler(commands=['add'])
def start_adding_expense(message):
    chat_id = message.chat.id

    # Check if username exists; if not, ask for it
    if chat_id not in user_data or user_data[chat_id]['username'] is None:
        bot.send_message(chat_id, "Please provide your username first by typing /start.")
        return

    # Proceed to category selection
    send_category_buttons(message)

# Show category buttons
def send_category_buttons(message):
    chat_id = message.chat.id
    markup = types.ReplyKeyboardMarkup(row_width=2, one_time_keyboard=True)
    btns = [types.KeyboardButton(cat.capitalize()) for cat in categories]
    markup.add(*btns)
    msg = bot.send_message(chat_id, "Please choose a category:", reply_markup=markup)
    bot.register_next_step_handler(msg, choose_category)

# Handle the category selection and automatically proceed to ask for amount
def choose_category(message):
    chat_id = message.chat.id
    category = message.text.lower()
    if category not in categories:
        bot.reply_to(message, "Invalid category. Please choose from the available options.")
        send_category_buttons(message)  # Resend buttons if invalid
        return

    user_data[chat_id]['category'] = category
    # Remove keyboard and ask for amount immediately after category is chosen
    markup = types.ReplyKeyboardRemove(selective=False)
    bot.send_message(chat_id, "Please enter the amount spent:", reply_markup=markup)
    bot.register_next_step_handler(message, process_amount)

# Step 3: Process amount and ensure it's valid (greater than 0)
def process_amount(message):
    chat_id = message.chat.id
    try:
        amount = float(message.text)
        if amount <= 0:
            bot.send_message(chat_id, "Amount must be a positive number greater than 0. Please try again.")
            send_category_buttons(message)  # Restart process if invalid
            return

        category = user_data[chat_id]['category']
        add_or_merge_expense(chat_id, category, amount)
        bot.send_message(chat_id, f"Expense added for {user_data[chat_id]['username']}: {category} - {amount}")
    except ValueError:
        bot.send_message(chat_id, "Invalid amount. Please enter a valid number.")
        bot.register_next_step_handler(message, process_amount)

# Function to generate user-specific weekly or monthly summary, chart, and send it
def generate_user_summary(chat_id, period='week'):
    if not os.path.exists(excel_file):
        bot.send_message(chat_id, "No expenses recorded yet.")
        return

    df = pd.read_excel(excel_file)
    df['date'] = pd.to_datetime(df['date'])
    username = user_data[chat_id]['username']

    now = pd.to_datetime('now')

    # Filter data based on period and user
    if period == 'week':
        period_filter = df[(df['date'] >= now - pd.to_timedelta(7, unit='d')) & (df['user'] == username)]
        period_name = 'Week'
    elif period == 'month':
        period_filter = df[(df['date'].dt.month == now.month) & (df['user'] == username)]
        period_name = 'Month'

    if period_filter.empty:
        bot.send_message(chat_id, f"No expenses recorded for the last {period_name.lower()}.")
        return

    # Group by category and sum the amounts
    grouped = period_filter.groupby(['category'])['amount'].sum()

    # Calculate the total spent
    total_amount = grouped.sum()

    # Generate a user-friendly text summary
    text_summary = f"Expense Summary for {username} for the Last {period_name}:\n"
    for category, amount in grouped.items():
        text_summary += f"  {category}: {amount}\n"
    text_summary += f"\nTotal spent: {total_amount}"

    bot.send_message(chat_id, text_summary)

    # Generate and send the chart
    grouped.plot(kind='bar', stacked=True, figsize=(10, 6))
    plt.title(f'Expense Summary for {username} for the Last {period_name}')
    plt.xlabel('Categories')
    plt.ylabel('Amount')
    plt.tight_layout()

    # Save the chart as an image
    chart_file = f'{period_name.lower()}_expense_summary_{username}.png'
    plt.savefig(chart_file)
    plt.close()

    # Send the chart to the user
    with open(chart_file, 'rb') as photo:
        bot.send_photo(chat_id, photo)

# Function to generate weekly or monthly report for all users
def generate_report_for_all_users(period='week'):
    if not os.path.exists(excel_file):
        return "No expenses recorded yet."

    df = pd.read_excel(excel_file)
    df['date'] = pd.to_datetime(df['date'])

    now = pd.to_datetime('now')

    # Filter data based on period
    if period == 'week':
        period_filter = df[df['date'] >= now - pd.to_timedelta(7, unit='d')]
        period_name = 'Week'
    elif period == 'month':
        period_filter = df[df['date'].dt.month == now.month]
        period_name = 'Month'

    if period_filter.empty:
        return f"No expenses recorded in the last {period_name.lower()}."

    # Group by user and category, and sum the amounts
    grouped = period_filter.groupby(['user', 'category'])['amount'].sum().unstack()

    # Calculate total spent by each user and overall total
    total_per_user = period_filter.groupby('user')['amount'].sum()
    overall_total = total_per_user.sum()

    # Generate a user-friendly text summary with percentages
    text_summary = f"Expense Summary for the Last {period_name}:\n"
    for user, total_amount in total_per_user.items():
        percentage = (total_amount / overall_total) * 100 if overall_total > 0 else 0
        text_summary += f"\nUser: {user}\n  Total spent: {total_amount} ({percentage:.2f}% of total)\n"
        for category, amount in grouped.loc[user].items():
            if pd.notna(amount):
                text_summary += f"  {category}: {amount}\n"

    # Generate and save the chart
    grouped.plot(kind='bar', stacked=True, figsize=(10, 6))
    plt.title(f'Expense Summary for the Last {period_name}')
    plt.xlabel('Users')
    plt.ylabel('Amount')
    plt.tight_layout()

    chart_file = f'{period_name.lower()}_expense_summary.png'
    plt.savefig(chart_file)
    plt.close()

    return text_summary, chart_file

# Function to send weekly report to all users
def send_weekly_report():
    text_summary, chart_file = generate_report_for_all_users(period='week')

    for chat_id in user_data:
        bot.send_message(chat_id, text_summary)
        with open(chart_file, 'rb') as photo:
            bot.send_photo(chat_id, photo)

# Function to send monthly report to all users
def send_monthly_report():
    text_summary, chart_file = generate_report_for_all_users(period='month')

    for chat_id in user_data:
        bot.send_message(chat_id, text_summary)
        with open(chart_file, 'rb') as photo:
            bot.send_photo(chat_id, photo)

# Command to get the weekly total with chart for the specific user
@bot.message_handler(commands=['week_total'])
def send_week_total(message):
    chat_id = message.chat.id
    generate_user_summary(chat_id, period='week')

# Command to get the monthly total with chart for the specific user
@bot.message_handler(commands=['month_total'])
def send_month_total(message):
    chat_id = message.chat.id
    generate_user_summary(chat_id, period='month')

# Scheduler to send reports every week and month
scheduler = BackgroundScheduler()
scheduler.add_job(send_weekly_report, 'cron', day_of_week='mon', hour=0, minute=0)  # Every Monday at 00:00 AM
scheduler.add_job(send_monthly_report, 'cron', day=1, hour=0, minute=0)  # On the 1st day of each month at 00:00 AM
scheduler.start()

# Start the bot
bot.polling()
