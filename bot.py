import logging
import os
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# Attempt to import GigaChat SDK (adjust as needed)
try:
    from gigachat import GigaChat
    from gigachat.models import Chat, Messages, MessagesRole
except ImportError:
    GigaChat = None
    # logger is not defined yet, so we can't use it here.
    # Consider moving logger setup earlier or handling this differently.
    print("WARNING: GigaChat SDK not found. Please install and configure.")

from docxtpl import DocxTemplate
import io

# Load environment variables from .env file
load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
GIGACHAT_API_KEY = os.getenv("GIGACHAT_API_KEY") # Or the correct variable name for GigaChat credentials

# Enable logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Sends a welcome message when the /start command is issued."""
    user = update.effective_user
    await update.message.reply_html(
        rf"Hi {user.mention_html()}! Welcome to the GigaChat Document Bot.",
    )
    await update.message.reply_text(
        "Here's how to use me:\n"
        "- Use /upload_prompt to upload a .txt prompt file.\n"
        "- Use /upload_template to upload a .docx template file.\n"
        "- Use /list_prompts to see your uploaded prompts.\n"
        "- Use /list_templates to see your uploaded templates.\n"
        "- Use /select_prompt <prompt_name> to choose an active prompt.\n"
        "- Use /select_template <template_name> to choose an active template.\n"
        "- Use /status to see your current selections.\n"
        "- Send me any text message, and I'll process it with GigaChat using your active prompt and template!"
    )

def main() -> None:
    """Start the bot."""
    # Create the Application and pass it your bot's token.
    if not TELEGRAM_BOT_TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN not found in environment variables!")
        return

    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    # on different commands - answer in Telegram
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("upload_prompt", upload_prompt_handler))
    application.add_handler(CommandHandler("upload_template", upload_template_handler))
    application.add_handler(CommandHandler("list_prompts", list_prompts_handler))
    application.add_handler(CommandHandler("list_templates", list_templates_handler))
    application.add_handler(CommandHandler("select_prompt", select_prompt_handler))
    application.add_handler(CommandHandler("select_template", select_template_handler))
    application.add_handler(CommandHandler("status", status_handler))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    application.add_error_handler(error_handler)

    # Run the bot until the user presses Ctrl-C
    logger.info("Starting bot...")
    application.run_polling()

if __name__ == "__main__":
    main()

# --- User Data Management Functions ---
import json # Make sure json is imported

USER_DATA_PATH = "user_data"

def get_user_dir(user_id: int) -> str:
    """Returns the path to the user's data directory, creating it if it doesn't exist."""
    user_dir = os.path.join(USER_DATA_PATH, str(user_id))
    os.makedirs(user_dir, exist_ok=True)
    os.makedirs(os.path.join(user_dir, "prompts"), exist_ok=True)
    os.makedirs(os.path.join(user_dir, "templates"), exist_ok=True)
    return user_dir

def get_user_settings_file(user_id: int) -> str:
    """Returns the path to the user's settings file."""
    return os.path.join(get_user_dir(user_id), "settings.json")

def load_user_settings(user_id: int) -> dict:
    """Loads user settings, returning default if not found."""
    settings_file = get_user_settings_file(user_id)
    if os.path.exists(settings_file):
        with open(settings_file, "r") as f:
            try:
                return json.load(f)
            except json.JSONDecodeError:
                return {"active_prompt": None, "active_template": None}
    return {"active_prompt": None, "active_template": None}

def save_user_settings(user_id: int, settings: dict) -> None:
    """Saves user settings."""
    settings_file = get_user_settings_file(user_id)
    with open(settings_file, "w") as f:
        json.dump(settings, f, indent=4)

async def save_user_file(user_id: int, file_id: str, file_name: str, file_type: str, context: ContextTypes.DEFAULT_TYPE) -> str | None:
    """Downloads and saves a file (prompt or template) for a user."""
    user_dir = get_user_dir(user_id)
    if file_type == "prompt":
        # Ensure it's a .txt file
        if not file_name.lower().endswith(".txt"):
            return "Invalid file type for prompt. Please upload a .txt file."
        save_path_dir = os.path.join(user_dir, "prompts")
    elif file_type == "template":
        # Ensure it's a .docx file
        if not file_name.lower().endswith(".docx"):
            return "Invalid file type for template. Please upload a .docx file."
        save_path_dir = os.path.join(user_dir, "templates")
    else:
        return "Invalid file type specified."

    # Sanitize file_name to prevent directory traversal issues
    file_name = os.path.basename(file_name)
    save_path = os.path.join(save_path_dir, file_name)

    try:
        bot_file = await context.bot.get_file(file_id)
        await bot_file.download_to_drive(save_path)
        logger.info(f"{file_type.capitalize()} '{file_name}' saved for user {user_id} to {save_path}")
        return None # No error message means success
    except Exception as e:
        logger.error(f"Error saving {file_type} for user {user_id}: {e}")
        return f"Could not save your {file_type}. Error: {e}"

def list_user_files(user_id: int, file_type: str) -> list[str]:
    """Lists uploaded files of a specific type for a user."""
    user_dir = get_user_dir(user_id) # Ensures directory exists
    files_dir = os.path.join(user_dir, f"{file_type}s") # e.g., prompts, templates
    if os.path.exists(files_dir):
        return [f for f in os.listdir(files_dir) if os.path.isfile(os.path.join(files_dir, f))]
    return []

def set_active_file(user_id: int, filename: str, file_type: str) -> str:
    """Sets the active prompt or template for a user."""
    settings = load_user_settings(user_id)
    files_dir = os.path.join(get_user_dir(user_id), f"{file_type}s")

    # Sanitize filename
    filename = os.path.basename(filename)

    if not os.path.exists(os.path.join(files_dir, filename)):
        return f"{file_type.capitalize()} '{filename}' not found."

    if file_type == "prompt":
        settings["active_prompt"] = filename
    elif file_type == "template":
        settings["active_template"] = filename
    else:
        return "Invalid file type."

    save_user_settings(user_id, settings)
    return f"Active {file_type} set to '{filename}'."

def get_active_file_path(user_id: int, file_type: str) -> str | None:
    """Gets the full path of the active prompt or template file."""
    settings = load_user_settings(user_id)
    active_filename = settings.get(f"active_{file_type}")
    if active_filename:
        # Sanitize active_filename before joining path
        active_filename = os.path.basename(active_filename)
        return os.path.join(get_user_dir(user_id), f"{file_type}s", active_filename)
    return None

# --- End User Data Management Functions ---

# --- Command Handlers ---

async def upload_prompt_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles the /upload_prompt command. Expects a .txt file."""
    user_id = update.effective_user.id
    if not update.message.document:
        await update.message.reply_text("Please send a .txt file as a document to upload as a prompt.")
        return

    doc = update.message.document
    if not doc.file_name.lower().endswith(".txt"):
        await update.message.reply_text("Invalid file type. Please upload a .txt file for prompts.")
        return

    error_message = await save_user_file(user_id, doc.file_id, doc.file_name, "prompt", context)
    if error_message:
        await update.message.reply_text(error_message)
    else:
        await update.message.reply_text(f"Prompt '{doc.file_name}' uploaded successfully!")

async def upload_template_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles the /upload_template command. Expects a .docx file."""
    user_id = update.effective_user.id
    if not update.message.document:
        await update.message.reply_text("Please send a .docx file as a document to upload as a template.")
        return

    doc = update.message.document
    if not doc.file_name.lower().endswith(".docx"):
        await update.message.reply_text("Invalid file type. Please upload a .docx file for templates.")
        return

    error_message = await save_user_file(user_id, doc.file_id, doc.file_name, "template", context)
    if error_message:
        await update.message.reply_text(error_message)
    else:
        await update.message.reply_text(f"Template '{doc.file_name}' uploaded successfully!")

async def list_prompts_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles the /list_prompts command."""
    user_id = update.effective_user.id
    prompts = list_user_files(user_id, "prompt")
    if not prompts:
        await update.message.reply_text("You haven't uploaded any prompts yet. Use /upload_prompt to add one.")
        return
    message = "Your uploaded prompts:\n" + "\n".join([f"- {p}" for p in prompts])
    await update.message.reply_text(message)

async def list_templates_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles the /list_templates command."""
    user_id = update.effective_user.id
    templates = list_user_files(user_id, "template")
    if not templates:
        await update.message.reply_text("You haven't uploaded any templates yet. Use /upload_template to add one.")
        return
    message = "Your uploaded templates:\n" + "\n".join([f"- {t}" for t in templates])
    await update.message.reply_text(message)

async def select_prompt_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles the /select_prompt command."""
    user_id = update.effective_user.id
    if not context.args:
        await update.message.reply_text("Please provide a prompt filename. Usage: /select_prompt <filename.txt>")
        return

    prompt_name = " ".join(context.args) # Allow filenames with spaces, though it's simpler if they don't have them
    result_message = set_active_file(user_id, prompt_name, "prompt")
    await update.message.reply_text(result_message)

async def select_template_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles the /select_template command."""
    user_id = update.effective_user.id
    if not context.args:
        await update.message.reply_text("Please provide a template filename. Usage: /select_template <filename.docx>")
        return

    template_name = " ".join(context.args)
    result_message = set_active_file(user_id, template_name, "template")
    await update.message.reply_text(result_message)

async def status_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles the /status command."""
    user_id = update.effective_user.id
    settings = load_user_settings(user_id)
    active_prompt = settings.get("active_prompt", "Not set")
    active_template = settings.get("active_template", "Not set")
    await update.message.reply_text(f"Current status:\n- Active Prompt: {active_prompt}\n- Active Template: {active_template}")

# --- End Command Handlers ---
# --- GigaChat Integration ---
# Ensure the GigaChat library is imported.
# This might be 'import gigachat' or 'from gigachat import GigaChat', etc.
# For this example, let's assume a hypothetical GigaChat client.
# The user will need to install the correct SDK and adjust this part.

# try:
#     from gigachat import GigaChat # Replace with actual GigaChat SDK import
#     from gigachat.models import Chat, Messages, MessagesRole # Replace with actual models
# except ImportError:
#     logger.warning("GigaChat SDK not found. Please install it. Using placeholder for GigaChat interaction.")
#     GigaChat = None # Placeholder if SDK is not found

# Placeholder for GigaChat client initialization if needed globally
# gigachat_client = None
# if GigaChat and GIGACHAT_API_KEY: # Or GIGACHAT_CREDENTIALS
#     try:
#         # This initialization is hypothetical. Adjust based on the actual SDK.
#         # It might require credentials, api key, model name etc.
#         gigachat_client = GigaChat(credentials=GIGACHAT_API_KEY, verify_ssl_certs=False) # Example
#     except Exception as e:
#         logger.error(f"Failed to initialize GigaChat client: {e}")
# else:
#     logger.warning("GigaChat client could not be initialized. Check API key and SDK.")


async def query_gigachat(user_query: str, prompt_text: str) -> dict | None:
    """
    Queries GigaChat with the user's message and the selected prompt.
    Returns the JSON response from GigaChat or None if an error occurs.

    This is a placeholder function. Actual implementation depends on the GigaChat SDK.
    """
    if not GIGACHAT_API_KEY: # Or other credential check
        logger.error("GigaChat API key/credentials not configured.")
        return {"error": "GigaChat API key/credentials not configured."}

    # This is a HYPOTHETICAL structure for interacting with GigaChat.
    # Replace with the actual SDK usage.
    try:
        logger.info(f"Querying GigaChat. User query: '{user_query[:50]}...', Prompt: '{prompt_text[:50]}...'")

        # Example using a hypothetical SDK structure:
        # if not gigachat_client:
        #     logger.error("GigaChat client not initialized.")
        #     return {"error": "GigaChat client not initialized."}

        # payload = Chat(
        #     messages=[
        #         Messages(
        #             role=MessagesRole.SYSTEM, # Or .USER if the prompt is more like a user instruction
        #             content=prompt_text
        #         ),
        #         Messages(
        #             role=MessagesRole.USER,
        #             content=user_query
        #         )
        #     ],
        #     # model="GigaChat:latest", # Specify model if required by API
        #     # temperature=0.7,
        #     # ... other parameters
        # )
        # response = await gigachat_client.chat(payload) # Assuming async SDK call
        # return response.choices[0].message.content # This is highly dependent on SDK's response structure

        # --- Placeholder Response ---
        # Simulate a GigaChat response for development without live API.
        # In a real scenario, you would remove this and use the actual API call.
        logger.warning("Using P L A C E H O L D E R GigaChat response. Implement actual API call.")
        if "error" in user_query.lower(): # Simulate an error
             return {"error": "Simulated GigaChat API error."}

        # Simulate a successful response structure that docxtpl can use.
        # This should be a JSON object (Python dictionary).
        simulated_json_response = {
            "name": "John Doe",
            "item_list": [
                {"item": "Report A", "value": "123"},
                {"item": "Analysis B", "value": "456"}
            ],
            "details": "This is a sample detail section generated based on the query.",
            "user_query_summary": user_query[:100] + "..."
        }
        return simulated_json_response
        # --- End Placeholder Response ---

    except Exception as e:
        logger.error(f"Error querying GigaChat: {e}")
        return {"error": f"An error occurred while contacting GigaChat: {str(e)}"}

# --- End GigaChat Integration ---

# --- Core Message Processing for Document Generation ---

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles regular text messages to generate documents."""
    user_id = update.effective_user.id
    user_query = update.message.text

    logger.info(f"Received message from user {user_id}: {user_query}")

    # 1. Check for active prompt and template
    active_prompt_path = get_active_file_path(user_id, "prompt")
    active_template_path = get_active_file_path(user_id, "template")

    if not active_prompt_path:
        await update.message.reply_text("No active prompt selected. Please use /select_prompt <filename.txt>.")
        return
    if not active_template_path:
        await update.message.reply_text("No active template selected. Please use /select_template <filename.docx>.")
        return

    if not os.path.exists(active_prompt_path):
        await update.message.reply_text(f"Error: Active prompt file '{os.path.basename(active_prompt_path)}' not found. Please re-select or upload.")
        set_active_file(user_id, None, "prompt") # Reset invalid active prompt
        return
    if not os.path.exists(active_template_path):
        await update.message.reply_text(f"Error: Active template file '{os.path.basename(active_template_path)}' not found. Please re-select or upload.")
        set_active_file(user_id, None, "template") # Reset invalid active template
        return

    # 2. Retrieve prompt content
    try:
        with open(active_prompt_path, "r", encoding="utf-8") as f:
            prompt_text = f.read()
    except Exception as e:
        logger.error(f"Error reading prompt file {active_prompt_path} for user {user_id}: {e}")
        await update.message.reply_text(f"Error reading active prompt: {e}")
        return

    await update.message.reply_text("Processing your request with GigaChat and generating the document...")

    # 3. Query GigaChat
    gigachat_response = await query_gigachat(user_query, prompt_text)

    if not gigachat_response:
        await update.message.reply_text("Failed to get a response from GigaChat. Please try again later.")
        return
    if "error" in gigachat_response: # Check for functional error key from our gigachat wrapper
        await update.message.reply_text(f"GigaChat error: {gigachat_response['error']}")
        return
    if not isinstance(gigachat_response, dict):
        logger.error(f"GigaChat response is not a JSON object (dict): {type(gigachat_response)}")
        await update.message.reply_text("Received an unexpected response format from GigaChat. Cannot populate template.")
        return


    # 4. Populate template and send
    try:
        doc = DocxTemplate(active_template_path)
        # The context for docxtpl must be a dictionary. GigaChat response is assumed to be this.
        doc.render(gigachat_response) # gigachat_response is the context

        # Save to a BytesIO object to send without saving to disk temporarily
        file_stream = io.BytesIO()
        doc.save(file_stream)
        file_stream.seek(0) # Go to the beginning of the stream

        # Generate a filename for the output document
        base_template_name = os.path.basename(active_template_path)
        # remove .docx and add _output.docx
        output_filename = base_template_name.rsplit('.', 1)[0] + "_output.docx"


        await update.message.reply_document(
            document=file_stream,
            filename=output_filename,
            caption="Here is your generated document."
        )
        logger.info(f"Document '{output_filename}' generated and sent to user {user_id}")

    except FileNotFoundError:
        logger.error(f"Template file {active_template_path} not found during rendering for user {user_id}.")
        await update.message.reply_text("Error: The active template file was not found. Please select it again.")
        set_active_file(user_id, None, "template") # Reset invalid active template
    except Exception as e:
        logger.error(f"Error generating document for user {user_id}: {e}")
        await update.message.reply_text(f"An error occurred while generating the document: {e}")

# --- End Core Message Processing ---

# --- Generic Error Handler ---

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Log Errors caused by Updates."""
    logger.error(f"Update {update} caused error {context.error}", exc_info=context.error)
    # Optionally, notify the user that an unexpected error occurred
    if isinstance(update, Update) and update.effective_message:
        try:
            await update.effective_message.reply_text("An unexpected error occurred. The developers have been notified.")
        except Exception as e:
            logger.error(f"Failed to send generic error message to user: {e}")

# --- End Generic Error Handler ---
