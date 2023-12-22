import requests
import aiohttp
import aiofiles
import threading
import json
import jwt
import datetime
from deepseek_api.constants import API_URL
from deepseek_api.errors import EmptyEmailOrPasswordError, NotLoggedInError
                    
class DeepseekAPI:
    """
    An asynchronous class to interact with the Deepseek API.
    """

    def __init__(self, email: str, password: str, model_class: str = "deepseek_code", save_login: bool = False):
        """
        Constructor method for DeepseekAPI class.

        Initializes a DeepseekAPI instance with provided credentials and settings.

        Parameters:
        email (str): User's email for Deepseek account
        password (str): Password for user's Deepseek account
        model_class (str): Deepseek model to use, either 'deepseek_chat' or 'deepseek_code'
        save_login (bool): Whether to save credentials to login.json to avoid re-login

        """
        self.email = email
        self.password = password
        self.model_class = model_class
        self.save_login = save_login
        self.headers = {
            "Accept-Language": "en-IN,en;q=0.9",
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "DNT": "1",
            "Origin": "https://coder.deepseek.com",
            "Pragma": "no-cache",
            "Referer": "https://coder.deepseek.com/",
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-origin",
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome",
            "accept": "*/*",
            "content-type": "application/json",
            "sec-ch-ua": '"Google Chrome";v="119", "Chromium";v="119", "Not?A_Brand";v="24"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"Linux"',
            "x-app-version": "20231220.2",
        }

        self.credentials = {}
        self.session = None  # Initialized in the async context manager
        self._thread_timer = None # Initialized in the _schedule_update_token method

    async def __aenter__(self):
        """Initializes an aiohttp ClientSession and logs in.

        This method is called when entering an async context manager.
        It creates the aiohttp ClientSession used for making requests.
        It also calls the login() method to authenticate with Deepseek.

        Returns:
            Self - Returns itself to enable use as an async context manager.
        """
        self.session = aiohttp.ClientSession()
        await self.login()
        return self

    async def __aexit__(self, exc_type, exc, tb):
        """Closes the aiohttp ClientSession and cancels the scheduled token update.

        This method is called when exiting the async context manager. It closes
        the aiohttp ClientSession that was used for making requests to the API.

        It also cancels the scheduled token update that was created in
        __schedule_update_token() to periodically refresh the auth token.
        """
        await self.session.close()
        if self._thread_timer:
            self._thread_timer.cancel()

    async def _login(self):
        """Logs in the user by sending a POST request to the login API endpoint.

        Sends the login request with email, password and other required fields.
        Saves the credentials to a file if save_login is True.
        Returns the JSON response from the API.
        """
        if self.email == "" or self.password == "":
            raise EmptyEmailOrPasswordError

        json_data = {
            "email": self.email,
            "mobile": "",
            "password": self.password,
            "area_code": "",
        }

        async with self.session.post(
            API_URL.LOGIN, headers=self.headers, json=json_data
        ) as response:
            self.credentials = await response.json()
            self.headers["authorization"] = "Bearer " + self.get_token()

            if self.save_login:
                async with aiofiles.open("login.json", "w") as file:
                    await file.write(json.dumps(self.credentials))


            return await response.json()
        
    async def login(self):
        """Logs the user in by loading credentials from file or calling login API.

        If save_login is True, tries to load credentials from the login.json file.
        If file not found, calls _login() to login via API.

        If save_login is False, calls _login() to always login via API.

        Schedules an update token callback to refresh the token periodically.
        """
        if self.save_login:
            try:
                async with aiofiles.open("login.json", "r") as file:
                    content = await file.read()
                    self.credentials = json.loads(content)

                    self.set_authorization_header()
            except FileNotFoundError:
                await self._login()
        else:
            await self._login()
        # Schedule a callback to update the token periodically
        self._schedule_update_token()
        
    def _schedule_update_token(self):
        """Schedules a timer to refresh the JWT token before it expires.

        Decodes the current JWT token to get the 'exp' expiration time.
        Subtracts 1 hour from the 'exp' time to refresh the token early.
        Starts a Timer thread to call the _login() method when the expiration
        time is reached. This will refresh the token and update the authorization
        header with the new token.
        """
        # Decode the JWT token
        token = self.get_token()
        decoded_token = jwt.decode(token, options={"verify_signature": False})

        # Fetch the 'exp' value and subtract 1 hour (to be safe)
        exp_time = datetime.datetime.fromtimestamp(
            decoded_token["exp"]
        ) - datetime.timedelta(hours=1)

        self._thread_timer = threading.Timer(
            (exp_time - datetime.datetime.now()).total_seconds(), self._login
        )
        self._thread_timer.start()
        
    async def is_logged_in(self):
        """Check if user is logged in

        Returns:
            bool: True if logged in, False otherwise
        """
        if self.credentials:
            return True
        else:
            return False
        
    async def raise_for_not_logged_in(self):
        """Raise NotLoggedInError if user is not logged in

        Raises:
            NotLoggedInError: If user is not logged in
        """
        if not await self.is_logged_in():
            raise NotLoggedInError
        
    def set_authorization_header(self):
        """Sets the authorization header to a JWT token.
        
        Gets the JWT token by calling get_token() and prepends 'Bearer ' 
        to set the authorization header.
        """
        self.headers["authorization"] = "Bearer " + self.get_token()

    def get_token(self):
        """Get token

        Returns:
            str: JWT Authorization token
        """
        return self.get_credentials()["data"]["user"]["token"]
    
    def get_credentials(self):
        """Get credentials

        Returns:
            dict: Credentials JSON data from login response
        """
        return self.credentials

    async def new_chat(self):
        """Start a new chat asynchronously"""
        
        params = {
            "session_id": "1",
        }
        
        json_data = {
            'model_class': self.model_class,
            'append_welcome_message': False,
        }
        
        async with self.session.post(
            API_URL.CLEAR_CONTEXT,
            params=params,
            headers=self.headers,
            json=json_data
        ) as response:
            return await response.json()


    async def chat(self, message: str):
        """Chat asynchronously with the Deepseek API.

        Sends a chat message to the Deepseek API and yields the response.

        Args:
            message (str): The chat message to send.

        Yields:
            dict: The JSON response from the API for each chat message.
        """

        json_data = {
            "message": message,
            "stream": True,
            "model_class": self.model_class,
            "model_preference": None,
            "temperature": 0,
        }

        async with self.session.post(
            API_URL.CHAT, headers=self.headers, json=json_data
        ) as response:
            # Check if the request was successful (status code 200)
            response.raise_for_status()

            # Iterate over the content asynchronously
            async for data in response.content:
                line = data.decode().strip().replace("data: ", "")
                if line:
                    line = json.loads(line)
                    if line.get("payload", None) is None:
                        line["choices"][0]["delta"]["content"] = ""
                    yield line


class SyncDeepseekAPI:
    """
    A synchronous class to interact with the Deepseek API.
    """

    def __init__(self, email: str, password: str, model_class: str = "deepseek_code", save_login: bool = False):
        """
        Constructor method for DeepseekAPI class.

        Initializes a DeepseekAPI instance with provided credentials and settings.

        Parameters:
        email (str): User's email for Deepseek account
        password (str): Password for user's Deepseek account
        model_class (str): Deepseek model to use, either 'deepseek_chat' or 'deepseek_code'
        save_login (bool): Whether to save credentials to login.json to avoid re-login

        """
        self.email = email
        self.password = password
        self.model_class = model_class
        self.save_login = save_login
        self.headers = {
            "Accept-Language": "en-IN,en;q=0.9",
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "DNT": "1",
            "Origin": "https://coder.deepseek.com",
            "Pragma": "no-cache",
            "Referer": "https://coder.deepseek.com/",
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-origin",
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome",
            "accept": "*/*",
            "content-type": "application/json",
            "sec-ch-ua": '"Google Chrome";v="119", "Chromium";v="119", "Not?A_Brand";v="24"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"Linux"',
            "x-app-version": "20231220.2",
        }

        self.credentials = {}
        self._thread_timer = None # Initialized in the _schedule_update_token method
        self.session = requests.Session()
        self.login()
    
    def __del__(self):
        """Destructor method for DeepseekAPI class.

        Closes the requests Session that was used for making requests to the API.
        """
        self.session.close()
        if self._thread_timer:
            self._thread_timer.cancel()
        
    def _login(self):
        """Logs in the user by sending a POST request to the login API endpoint.

        Sends the login request with email, password and other required fields.
        Saves the credentials to a file if save_login is True.
        Returns the JSON response from the API.
        
        Raises:
            EmptyEmailOrPasswordError: If the email or password is not provided.
            requests.exceptions.RequestException: If the login request fails.
            
        Returns:
            dict: Credentials JSON data from login response
        """
        if self.email == "" or self.password == "":
            raise EmptyEmailOrPasswordError

        json_data = {
            "email": self.email,
            "mobile": "",
            "password": self.password,
            "area_code": "",
        }

        response = self.session.post(
            API_URL.LOGIN, headers=self.headers, json=json_data
        )
        self.credentials = response.json()
        self.headers["authorization"] = "Bearer " + self.get_token()

        if self.save_login:
            with open("login.json", "w") as file:
                file.write(json.dumps(self.credentials))

        return response.json()
    
    def login(self):
        """Logs the user in by loading credentials from file or calling login API.

        If save_login is True, tries to load credentials from the login.json file.
        If file not found, calls _login() to login via API.

        If save_login is False, calls _login() to always login via API.

        Schedules an update token callback to refresh the token periodically.
        """
        if self.save_login:
            try:
                with open("login.json", "r") as file:
                    content = file.read()
                    self.credentials = json.loads(content)

                    self.set_authorization_header()
            except FileNotFoundError:
                self._login()
        else:
            self._login()
        # Schedule a callback to update the token periodically
        self._schedule_update_token()
        
    def _schedule_update_token(self):
        """Schedules a timer to refresh the JWT token before it expires.

        Decodes the current JWT token to get the 'exp' expiration time.
        Subtracts 1 hour from the 'exp' time to refresh the token early.
        Starts a Timer thread to call the _login() method when the expiration
        time is reached. This will refresh the token and update the authorization
        header with the new token.
        """
        # Decode the JWT token
        token = self.get_token()
        decoded_token = jwt.decode(token, options={"verify_signature": False})

        # Fetch the 'exp' value and subtract 1 hour (to be safe)
        exp_time = datetime.datetime.fromtimestamp(
            decoded_token["exp"]
        ) - datetime.timedelta(hours=1)

        self._thread_timer = threading.Timer(
            (exp_time - datetime.datetime.now()).total_seconds(), self._login
        )
        self._thread_timer.start()
        
            
    def is_logged_in(self):
        """Check if user is logged in

        Returns:
            bool: True if logged in, False otherwise
        """
        if self.credentials:
            return True
        else:
            return False
        
    def raise_for_not_logged_in(self):
        """Raise NotLoggedInError if user is not logged in

        Raises:
            NotLoggedInError: If user is not logged in
        """
        if not self.is_logged_in():
            raise NotLoggedInError
        
    def set_authorization_header(self):
        """Sets the authorization header to a JWT token.
        
        Gets the JWT token by calling get_token() and prepends 'Bearer ' 
        to set the authorization header.
        """
        self.headers["authorization"] = "Bearer " + self.get_token()
        
    def get_token(self):
        """Get token

        Returns:
            str: JWT Authorization token
        """
        return self.get_credentials()["data"]["user"]["token"]
    
    def get_credentials(self):
        """Get credentials

        Returns:
            dict: Credentials JSON data from login response
        """
        return self.credentials
    
    def new_chat(self):
        """Start a new chat synchronously"""
        
        params = {
            "session_id": "1",
        }
        
        json_data = {
            'model_class': self.model_class,
            'append_welcome_message': False,
        }
        
        response = self.session.post(
            API_URL.CLEAR_CONTEXT,
            params=params,
            headers=self.headers,
            json=json_data
        )
        return response.json()
    
    def chat(self, message: str):
        """Chat synchronously with the Deepseek API.

        Sends a chat message to the Deepseek API and yields the response.

        Args:
            message (str): The chat message to send.

        Yields:
            dict: The JSON response from the API for each chat message.
        """

        json_data = {
            "message": message,
            "stream": True,
            "model_class": self.model_class,
            "model_preference": None,
            "temperature": 0,
        }

        response = self.session.post(
            API_URL.CHAT, headers=self.headers, json=json_data
        )
        # Check if the request was successful (status code 200)
        response.raise_for_status()

        # Iterate over the content asynchronously
        for data in response.iter_content():
            line = data.decode().strip().replace("data: ", "")
            if line:
                line = json.loads(line)
                if line.get("payload", None) is None:
                    line["choices"][0]["delta"]["content"] = ""
                yield line
                