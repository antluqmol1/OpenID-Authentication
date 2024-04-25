import identity.web
import requests
from flask import Flask, redirect, render_template, request, session, url_for, flash
from flask_session import Session
from datetime import datetime
import app_config
import re
import phonenumbers

__version__ = "0.8.0"  # The version of this sample, for troubleshooting purpose

app = Flask(__name__)
app.config.from_object(app_config)
assert app.config["REDIRECT_PATH"] != "/", "REDIRECT_PATH must not be /"
Session(app)

# This section is needed for url_for("foo", _external=True) to automatically
# generate http scheme when this sample is running on localhost,
# and to generate https scheme when it is deployed behind reversed proxy.
# See also https://flask.palletsprojects.com/en/2.2.x/deploying/proxy_fix/
from werkzeug.middleware.proxy_fix import ProxyFix
app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)

app.jinja_env.globals.update(Auth=identity.web.Auth)  # Useful in template for B2C
auth = identity.web.Auth(
    session=session,
    authority=app.config["AUTHORITY"],
    client_id=app.config["CLIENT_ID"],
    client_credential=app.config["CLIENT_SECRET"],
)

@app.route("/")
def index():
    if not (app.config["CLIENT_ID"] and app.config["CLIENT_SECRET"]):
        return render_template('config_error.html')
    if auth.get_user():
        # User is authenticated
        return render_template('index.html', user=auth.get_user(), version=__version__)
    return render_template('index.html', user={}, version = __version__, **auth.log_in(
        scopes=app_config.SCOPE, # Have user consent to scopes during log-in
        redirect_uri=url_for("auth_response", _external=True), # Optional. If present, this absolute URL must match your app's redirect_uri registered in Azure Portal
        prompt="select_account",  # Optional. More values defined in  https://openid.net/specs/openid-connect-core-1_0.html#AuthRequest
        ))

@app.route("/login")
def login():
    return render_template("login.html", user={}, version=__version__, **auth.log_in(
        scopes=app_config.SCOPE, # Have user consent to scopes during log-in
        redirect_uri=url_for("auth_response", _external=True), # Optional. If present, this absolute URL must match your app's redirect_uri registered in Microsoft Entra admin center
        prompt="select_account",  # Optional.
        ))

@app.route(app_config.REDIRECT_PATH)
def auth_response():
    result = auth.complete_log_in(request.args)
    if "error" in result:
        return render_template("auth_error.html", result=result)
    return redirect(url_for("index"))

@app.route("/profile", methods=["GET"])
def get_profile():
    # Shows error message for unauthenticated users when accessing restricted pages & content
    if not auth.get_user():
        return redirect(url_for("login"))
    # TODO: Check that the user is loggen in and add credentials to the http request.
    token = auth.get_token_for_user(app_config.SCOPE)
    if "error" in token:
        return redirect(url_for("index"))
    result = requests.get(
        'https://graph.microsoft.com/v1.0/me',
        headers={'Authorization': 'Bearer ' + token['access_token']},
    )

    return render_template('profile.html', user=result.json(), result=None)

@app.route("/profile", methods=["POST"])
def post_profile():
    # Shows error message for unauthenticated users when accessing restricted pages & content
    if not auth.get_user():
        return redirect(url_for("login"))
    # TODO: check that the user is logged in and add credentials to the http request.
    token = auth.get_token_for_user(app_config.SCOPE)
    if "error" in token:
        return redirect(url_for("index"))

    # ~~~~ Formatting stuff for the form ~~~~
    birthday_str = request.form.get('birthday')
    if birthday_str:
        # Convert the date string to a datetime object assuming it's in 'YYYY-MM-DD' format
        birthday_dt = datetime.strptime(birthday_str, '%Y-%m-%d')
        # Format it to ISO 8601 string with UTC time (midnight)
        formatted_birthday = birthday_dt.strftime('%Y-%m-%dT00:00:00Z')
    else:
        formatted_birthday = None
    
    raw_other_mails = request.form.get('otherMails', '')
    # Create a list of cleaned email addresses, ignoring any empty strings
    other_mails = [email.strip() for email in raw_other_mails.split(',') if email.strip() and '@' in email]
    
    mail = request.form.get('mail', '').strip()
    if not mail or not re.match(r"[^@]+@[^@]+\.[^@]+", mail):
        # Handle error: redirect, flash a message, or return an error response
        flash('Invalid email address.', 'error')

    raw_phone = request.form.get('businessPhones', '').strip()

    # Validate and format the Business Phone number
    try:
        if raw_phone:
            phone_number = phonenumbers.parse(raw_phone, None)
            if not phonenumbers.is_valid_number(phone_number):
                raise ValueError("Invalid phone number.")
            # Format the number in international format
            formatted_phone = phonenumbers.format_number(phone_number, phonenumbers.PhoneNumberFormat.E164)
            business_phones = [formatted_phone]
        else:
            business_phones = []
    except phonenumbers.NumberParseException:
        flash('Invalid phone number format. Please enter a valid number.', 'error')
        return redirect(url_for('update_profile'))  # Redirect to profile update page
    except ValueError as e:
        flash(str(e), 'error')
        return redirect(url_for('update_profile'))

    # ~~~~      ~~~~

    # user_data_to_update = {
    #     "displayName": request.form.get("displayName"),
    #     "givenName": request.form.get("givenName") or None,  # Handle 'None' strings properly
    #     "surname": request.form.get("surname") or None,
    #     "mobilePhone": request.form.get("mobilePhone") or None,
    #     "businessPhones": business_phones,
    #     "mail": mail,
    #     "otherMails": other_mails,
    #     "birthday": formatted_birthday,
    #     "city": request.form.get("city") or None,
    #     "country": request.form.get("country"),
    #     "preferredLanguage": request.form.get("preferredLanguage") or None
    # }

     # Validate and sanitize the user ID
    user_id = request.form.get("id")
    if not user_id:
        return "Invalid user ID", 400

    # Prepare headers for HTTP request
    headers = {'Authorization': 'Bearer ' + token['access_token']}
    
    # Prepare the JSON payload from form data, ensuring keys match expected API parameters
    user_data_to_update = {
        "mobilePhone": request.form.get("mobilePhone") or None,
        "businessPhones": business_phones,
        "preferredLanguage": request.form.get("preferredLanguage") or None,
        "otherMails": other_mails,
    }

    # If user is authenticated and token retrieval is succesful We proceed with the request
    result = requests.patch(
        f'https://graph.microsoft.com/v1.0/users/{user_id}',
        headers=headers,
        json=user_data_to_update
        # 'https://graph.microsoft.com/v1.0/users/' + request.form.get("id"),
        # headers={'Authorization': 'Bearer ' + token['access_token']},
        # json = request.form.to_dict()
        # json=user_data_to_update
    )
    if result.status_code != 200:
        return f"Error updating profile: {result.text}", result.status_code

    profile_response = requests.get(
        'https://graph.microsoft.com/v1.0/me',
        headers=headers
    )

    # Handle possible GET request failure
    if profile_response.status_code != 200:
        return f"Error fetching profile: {profile_response.text}", profile_response.status_code

    return render_template('profile.html',
                           user=profile_response.json(),
                           result=result.json())

@app.route("/logout")
def logout():
    return redirect(auth.log_out(url_for("index", _external=True)))

@app.route("/users")
def get_users():
    # Shows error message for unauthenticated users when accessing restricted pages & content
    if not auth.get_user():
        return redirect(url_for("login"))
    # TODO: Check that user is logged in and add credentials to the request.
    token = auth.get_token_for_user(app_config.SCOPE)
    if "error" in token:
        return redirect(url_for("index"))
    result = requests.get(
        'https://graph.microsoft.com/v1.0/users',
        headers={'Authorization': 'Bearer ' + token['access_token']},
    )
    return render_template('users.html', result=result.json())

@app.route("/call_downstream_api")
def call_downstream_api():
    # Shows error message for unauthenticated users when accessing restricted pages & content
    if not auth.get_user():
        return redirect(url_for("login"))
    token = auth.get_token_for_user(app_config.SCOPE)
    if "error" in token:
        return redirect(url_for("index"))
    # Use access token to call downstream api
    api_result = requests.get(
        app_config.ENDPOINT,
        headers={'Authorization': 'Bearer ' + token['access_token']},
        timeout=30,
    ).json()
    return render_template('display.html', result=api_result)


if __name__ == "__main__":
    app.run()
