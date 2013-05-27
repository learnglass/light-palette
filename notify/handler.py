from __future__ import with_statement
# Copyright (C) 2013 Google Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Request Handler for /notify endpoint."""

__author__ = 'alainv@google.com (Alain Vongsouvanh)'



import io
import StringIO
import json
import logging
import webapp2

from apiclient.http import MediaIoBaseUpload
from oauth2client.appengine import StorageByKeyName

from model import Credentials
from model import Picture
import util
import Image
import imaging
from google.appengine.ext import blobstore
from google.appengine.api import files


class NotifyHandler(webapp2.RequestHandler):
  """Request Handler for notification pings."""

  def post(self):
    """Handles notification pings."""
    logging.info('Got a notification with payload %s', self.request.body)
    data = json.loads(self.request.body)
    userid = data['userToken']
    # TODO: Check that the userToken is a valid userToken.
    self.mirror_service = util.create_service(
        'mirror', 'v1',
        StorageByKeyName(Credentials, userid, 'credentials').get())
    if data.get('collection') == 'locations':
      self._handle_locations_notification(data)
    elif data.get('collection') == 'timeline':
      self._handle_timeline_notification(data)

  def _handle_locations_notification(self, data):
    """Handle locations notification."""
    location = self.mirror_service.locations().get(id=data['itemId']).execute()
    text = 'New location is %s, %s' % (location.get('latitude'),
                                       location.get('longitude'))
    body = {
        'text': text,
        'location': location,
        'menuItems': [{'action': 'NAVIGATE'}],
        'notification': {'level': 'DEFAULT'}
    }
    self.mirror_service.timeline().insert(body=body).execute()

  def _handle_timeline_notification(self, data):
    """Handle timeline notification."""
    for user_action in data.get('userActions', []):
      if user_action.get('type') == 'SHARE':
        # Fetch the timeline item.
        item = self.mirror_service.timeline().get(id=data['itemId']).execute()
        attachments = item.get('attachments', [])
        media = None
        if attachments:
          # Get the first attachment on that timeline item and do stuff with it.
          attachment = self.mirror_service.timeline().attachments().get(
              itemId=data['itemId'],
              attachmentId=attachments[0]['id']).execute()
          resp, content = self.mirror_service._http.request(
              attachment['contentUrl'])
          if resp.status == 200:
            im_data = io.BytesIO(content)
            im_copy = io.BytesIO(content)
            im = Image.open(im_data)
            cf = imaging.ColorFinder(im)
            top = imaging.ColorUtil.generate_color_panes(tuple(cf.strategy_enhanced_complements()))
            output = StringIO.StringIO()
            top.save(output, format="JPEG")
            contents = io.BytesIO(output.getvalue())
            contents_copy = io.BytesIO(output.getvalue())
            output.close()

            upload = Picture(parent=Picture.picture_key(str(data['userToken'])))
            upload.owner = str(data['userToken'])
            file_name = files.blobstore.create(mime_type='image/jpeg')
            with files.open(file_name, 'a') as f:
                f.write(im_copy.read())
            files.finalize(file_name)
            picture_blob_key = files.blobstore.get_blob_key(file_name)
            upload.picture = str(picture_blob_key)

            palette_name = files.blobstore.create(mime_type='image/jpeg')
            with files.open(palette_name, 'a') as f:
                f.write(contents_copy.read())
            files.finalize(palette_name)
            palette_blob_key = files.blobstore.get_blob_key(palette_name)
            upload.palette = str(palette_blob_key)
            upload.put()

            media = MediaIoBaseUpload(
                contents, mimetype='image/jpeg',
                resumable=True)
            body = {
                'notification': {'level': 'DEFAULT'},
                'menuItems': [{'action': 'SHARE'}, {'action': 'DELETE'}]
            }
            self.mirror_service.timeline().insert(
                body=body, media_body=media).execute()
            self.mirror_service.timeline().delete(id=data['itemId']).execute()
          else:
            logging.info('Unable to retrieve attachment: %s', resp.status)
        # Only handle the first successful action.
        break
      else:
        logging.info(
            "I don't know what to do with this notification: %s", user_action)


NOTIFY_ROUTES = [
    ('/notify', NotifyHandler)
]
