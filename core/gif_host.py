import requests
import sys
from io import BytesIO
from pprint import pprint
from imgurpython.imgur.models.gallery_image import GalleryImage
from imgurpython.helpers.error import ImgurClientError

import core.hosts.imgur
from core import constants as consts
from core.gif import Gif
from core.regex import REPatterns
from core.hosts.imgur import ImgurClient
from core.hosts.gfycat import Gfycat as GfycatClient
from core.hosts.streamable import StreamableClient
from core.credentials import CredentialsLoader
from core.file import get_duration
from core import upload

creds = CredentialsLoader.get_credentials()
imgur = ImgurClient.get()
gfycat = GfycatClient.get()
streamable = StreamableClient.get()

class GifHost:
    type = None

    def __init__(self, context):
        self.context = context

    def analyze(self):
        raise NotImplemented

    def reverse(self):
        raise NotImplemented

    def upload_gif(self, gif):
        raise NotImplemented

    def upload_video(self, video):
        raise NotImplemented

    def get_gif(self):
        """Return info about the gif for checking the db"""
        if self.id:
            return Gif(self.type, self.id, nsfw=self.context.nsfw)
        else:
            return None

    @classmethod
    def open(cls, context, reddit):
        url = context.url
        # Imgur
        if REPatterns.imgur.findall(url):
            return ImgurGif(context)
        # Gfycat
        if REPatterns.gfycat.findall(url):
            return GfycatGif(context)
        # Reddit Gif
        if REPatterns.reddit_gif.findall(url):
            return RedditGif(context)
        # Reddit Vid
        if REPatterns.reddit_vid.findall(url):
            return RedditVid(context, reddit)
        # Streamable
        if REPatterns.streamable.findall(url):
            return Streamable(context)

        print("Unknown URL Type", url)
        return None


class ImgurGif(GifHost):
    type = consts.IMGUR

    def __init__(self, context):
        super(ImgurGif, self).__init__(context)
        self.uploader = consts.IMGUR
        # Retrieve the ID
        imgur_match = REPatterns.imgur.findall(self.context.url)[0]
        if imgur_match[4]: # Image match
            self.id = imgur_match[2]
        elif imgur_match[3]: # Gallery match
            gallery = imgur.gallery_item(imgur_match[3])
            if not isinstance(gallery, GalleryImage):
                self.id = gallery.images[0]['id']
            else:
                self.id = gallery.id
        elif imgur_match[2]: # Album match
            album = imgur.get_album(imgur_match[2])
            self.id = album.images[0]['id']

        try:
            self.pic = imgur.get_image(self.id)  # take first image from gallery album
        except ImgurClientError as e:
            if e.status_code == 404: # pic is deleted or otherwise missing
                self.pic = None
                self.id = None

    def analyze(self):
        """Analyze an imgur gif using the imgurpython library and determine how to reverse and upload"""

        # pprint(vars(self.pic))

        if not self.pic.animated:
            print("Not a gif!")
            return False
        r = requests.get(self.pic.mp4)
        duration = get_duration(BytesIO(r.content))


        if duration < 30:  # likely uploaded as a mp4, we should reupload through that
            self.url = self.pic.mp4
            return consts.VIDEO
        else:               # has to have been a gif
            self.url = self.pic.gifv[:-1]
            with requests.get(self.url, stream=True) as r:
                size = sum(len(chunk) for chunk in r.iter_content(8196))
            # Convert to MB
            size = size / 1000000
            print("size in MB", size)
            # Due to gifski bloat, we may need to redirect to gfycat
            if size > 175:
                self.uploader = consts.GFYCAT
            return consts.GIF

    def upload_video(self, video):
        return core.hosts.imgur.imgurupload(video, consts.VIDEO, nsfw=self.context.nsfw)


    def upload_gif(self, gif):
        if self.uploader == consts.IMGUR:
            return core.hosts.imgur.imgurupload(gif, consts.GIF, nsfw=self.context.nsfw)
        elif self.uploader == consts.GFYCAT:
            return gfycat.upload(gif, consts.GIF, nsfw=self.context.nsfw)

class GfycatGif(GifHost):
    type = consts.GFYCAT

    def __init__(self, context):
        super(GfycatGif, self).__init__(context)
        self.id = REPatterns.gfycat.findall(context.url)[0]
        self.pic = gfycat.get_gfycat(self.id)
        self.url = self.pic["gfyItem"]["mp4Url"]

    def analyze(self):
        return consts.VIDEO

    def upload_video(self, video):
        return gfycat.upload(video, consts.VIDEO, nsfw=self.context.nsfw)

class RedditGif(GifHost):
    type = consts.REDDITGIF

    def __init__(self, context):
        super(RedditGif, self).__init__(context)
        self.id = REPatterns.reddit_gif.findall(context.url)[0]
        self.url = context.url

    def analyze(self):
        # print(self.url)
        # input()

        return consts.GIF
    def upload_gif(self, gif):
        return core.hosts.imgur.imgurupload(gif, consts.GIF)

class RedditVid(GifHost):
    type = consts.REDDITVIDEO

    def __init__(self, context, reddit):
        super(RedditVid, self).__init__(context)
        self.uploader = consts.IMGUR
        self.id = REPatterns.reddit_vid.findall(self.context.url)[0]
        # TODO: Apparently praw has this data, rewrite to use that
        headers = {"User-Agent": consts.spoof_user_agent}
        # Follow redirect to post URL
        r = requests.get(self.context.url, headers=headers)
        submission_id = REPatterns.reddit_submission.findall(r.url)
        if submission_id:
            submission = reddit.submission(id=REPatterns.reddit_submission.findall(r.url)[0][1])
            if submission.is_video:
                self.url = submission.media['reddit_video']['fallback_url']
                print(self.url)

    def analyze(self):
        # print(self.url)
        # input()
        r = requests.get(self.url)
        duration = get_duration(BytesIO(r.content))
        if duration <= 30:  # likely uploaded as a mp4, reupload through imgur
            self.uploader = consts.IMGUR
            return consts.VIDEO
        elif duration <= 60: # fallback to gfycat
            self.uploader = consts.GFYCAT
            return consts.VIDEO
        else:  # fallback as a gif, upload to gfycat
            # I would like to be able to predict a >200MB GIF file size and switch from
            # Imgur to Gfycat as a result
            self.uploader = consts.GFYCAT
            return consts.GIF

    def upload_video(self, video):
        if self.uploader == consts.IMGUR:
            return core.hosts.imgur.imgurupload(video, consts.VIDEO, nsfw=self.context.nsfw)
        elif self.uploader == consts.GFYCAT:
            return gfycat.upload(video, consts.VIDEO, nsfw=self.context.nsfw)

    def upload_gif(self, gif):
        if self.uploader == consts.IMGUR:
            return core.hosts.imgur.imgurupload(gif, consts.GIF, nsfw=self.context.nsfw)
        elif self.uploader == consts.GFYCAT:
            return gfycat.upload(gif, consts.GIF, nsfw=self.context.nsfw)


class Streamable(GifHost):
    type = consts.STREAMABLE

    def __init__(self, context):
        super(Streamable, self).__init__(context)
        self.id = REPatterns.streamable.findall(self.context.url)[0]

    @property
    def url(self):
        return streamable.download_video(self.id)

    def analyze(self):
        return consts.VIDEO

    def upload_video(self, video):
        return streamable.upload_file(video, 'GifReversingBot - {}'.format(self.get_gif().url))



class LinkGif(GifHost):
    pass