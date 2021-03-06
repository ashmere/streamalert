"""
Copyright 2017-present, Airbnb Inc.

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

   http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
"""
from base64 import b64encode
from datetime import datetime
import hashlib
import hmac
import re
import urllib

import requests

from app_integrations import LOGGER
from app_integrations.apps.app_base import app, AppIntegration


class DuoApp(AppIntegration):
    """Duo base app integration. This is subclassed for the auth and admin APIs"""
    # Duo's api returns a max of 1000 logs per request
    _MAX_RESPONSE_LOGS = 1000

    @classmethod
    def _endpoint(cls):
        """Class method to return the endpoint to be used for this duo instance

        Returns:
            str: Path of the desired endpoint to query

        Raises:
            NotImplementedError: If the subclasses do not properly implement this method
        """
        raise NotImplementedError

    @classmethod
    def service(cls):
        return 'duo'

    def _generate_auth(self, hostname, params):
        """Duo requests must be signed each time.

        This has been largely borrowed/updated from here:
            https://github.com/duosecurity/duo_client_python/blob/master/duo_client/admin.py
        """
        formatted_date = datetime.utcnow().strftime('%a, %d %b %Y %H:%M:%S -0000')

        auth_string = '\n'.join([formatted_date, 'GET', hostname,
                                 self._endpoint(), urllib.urlencode(params)])

        try:
            signature = hmac.new(self._config['auth']['secret_key'],
                                 auth_string, hashlib.sha1)
        except TypeError:
            LOGGER.exception('Could not generate hmac signature')
            return False

        # Format the basic auth with integration key and the hmac hex digest
        basic_auth = ':'.join([self._config['auth']['integration_key'],
                               signature.hexdigest()])

        return {
            'Date': formatted_date,
            'Authorization': 'Basic {}'.format(b64encode(basic_auth)),
            'Host': hostname
        }

    def _gather_logs(self):
        """Gather the authentication log events."""
        hostname = self._config['auth']['api_hostname']
        full_url = 'https://{hostname}{endpoint}'.format(
            hostname=hostname,
            endpoint=self._endpoint()
        )

        return self._get_duo_logs(hostname, full_url)

    def _get_duo_logs(self, hostname, full_url):
        """Get all logs from the endpoint for this timeframe

        Returns:
            [
                {
                    'timestamp': <int:unix timestamp>,
                    'device': <str:device>,
                    'username': <str:username>,
                    'factor': <str:factor>,
                    'result': <str:result>,
                    'ip': <str:ip address>,
                    'new_enrollment': <bool:if event corresponds to enrollment>,
                    'integration': <str:integration>,
                    'location': {
                        'state': '<str:state>',
                        'city': '<str:city>',
                        'country': '<str:country>'
                    }
                }
            ]
        """
        # Get the last timestamp and add one to it to avoid duplicates
        # Sanity check mintime as unix timestamp, then transform to string
        params = {'mintime': str(int(self._last_timestamp + 1))}

        # Contstruct the headers for this request. Every request must be signed
        headers = self._generate_auth(hostname, params)
        if not headers:
            return False

        # Perform the request and get the list of logs
        response = requests.get(full_url, headers=headers, params=params)

        if not self._check_http_response(response):
            return False

        logs = response.json()['response']

        # Get the timestamp from the latest event. Duo produces these sequentially
        # so we can just extract the timestamp from the last item in the list
        self._last_timestamp = logs[-1]['timestamp']

        # Check if the max amount of logs was returned with this request. If the value
        # is not the max, then we are done polling logs for this timeframe
        # Setting _more_to_poll to true here will allow the caller to try to poll again
        self._more_to_poll = len(logs) >= self._MAX_RESPONSE_LOGS

        # Return the list of logs to the caller so they can be send to the batcher
        return logs

    def required_auth_info(self):
        return {
            'api_hostname':
                {
                    'description': ('the API hostname for this duosecurity instance. This should '
                                    'be in a format similar to \'api-abcdef12.duosecurity.com\''),
                    'format': re.compile(r'^api-[a-f0-9]{8}\.duosecurity\.com$')
                },
            'integration_key':
                {
                    'description': ('the integration key for this duosecurity Admin API. This '
                                    'should be in a format similar to \'DIABCDEFGHIJKLMN1234\''),
                    'format': re.compile(r'^DI[A-Z0-9]{18}$')
                },
            'secret_key':
                {
                    'description': ('the secret key for this duosecurity Admin API. This '
                                    'should a string of 40 alphanumeric characters'),
                    'format': re.compile(r'^[a-zA-Z0-9]{40}$')
                }
            }

    def _sleep_seconds(self):
        """Return the number of seconds this polling function should sleep for
        between requests to avoid failed requests. Duo allows for 2 API requests
        every 1 minute, so this should sleep every 2 polls.

        Returns:
            int: Number of seconds that this function shoud sleep for between requests
        """
        return abs((self._poll_count % 2) - 1) * 60


@app
class DuoAuthApp(DuoApp):
    """Duo authentication log app integration"""

    _DUO_AUTH_LOGS_ENDPOINT = '/admin/v1/logs/authentication'

    @classmethod
    def _type(cls):
        return 'auth'

    @classmethod
    def _endpoint(cls):
        """Class method to return the duo authentication log endpoint

        Returns:
            str: Path of the authentication endpoint to query
        """
        return cls._DUO_AUTH_LOGS_ENDPOINT


@app
class DuoAdminApp(DuoApp):
    """Duo administrator log app integration"""

    _DUO_ADMIN_LOGS_ENDPOINT = '/admin/v1/logs/administrator'

    @classmethod
    def _type(cls):
        return 'admin'

    @classmethod
    def _endpoint(cls):
        """Class method to return the duo administrator log endpoint

        Returns:
            str: Path of the administrator endpoint to query
        """
        return cls._DUO_ADMIN_LOGS_ENDPOINT
