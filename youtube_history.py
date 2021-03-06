#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
Downloads, analyzes, and reports all Youtube videos associated with a user's Google account.
"""
import json
import os
import pickle
import argparse
import getpass
import subprocess as sp
import sys 

from collections import namedtuple
from pathlib import Path
from webbrowser import open_new_tab
import pandas as pd
import numpy as np
from wordcloud import WordCloud, STOPWORDS
from flask import Flask
from flask import render_template
from bs4 import BeautifulSoup
from emoji import emoji_lis
from grapher import Grapher, flatten_without_nones
import googleapiclient.discovery
# API information
api_service_name = "youtube"
api_version = "v3"
# API key
DEVELOPER_KEY = "AIzaSyCEHEFHIpW-E0BrRtnn8RW9ceCP514M-kQ"
# API client
youtube = googleapiclient.discovery.build(
    api_service_name, api_version, developerKey = DEVELOPER_KEY)


app = Flask(__name__)

@app.route('/', methods=['GET', 'POST'])
def index():
    return render_template('index.html', analysis=analysis)

def launch_web():
    """
    Launches the HTML page with the analysis results 
    """
    app.debug = False
    app.secret_key = 'this key should be complex'

    file1 = os.path.join(analysis.raw, '00001.info.json')
    some_data = os.path.isfile(file1)
    if some_data:
        url = 'http://127.0.0.1:5000'
        open_new_tab(url)
        app.run()

def make_fake_series(title='N/A', webpage_url='N/A', **kwargs):
    params = ['title', 'webpage_url'] + list(kwargs.keys())
    Mock = namedtuple('MockSeries', params)
    return Mock(title, webpage_url, **kwargs)

class Uploader:
    def __init__(self, uploader, uploader_id, image_url, count):
        self.uploader = uploader
        self.uploader_id = uploader_id
        self.image_url = image_url
        self.count = count
        
    def get_contents(self):
        print(self.uploader)
        print(self.uploader_id)
        print(self.image_url)
        


class Analysis:
    """Analysis is responsible for downloading and analyzing the takeout data from google.

    :param takeout: Path to an unzipped Takeout folder downloaded from https://takeout.google.com/
    :type takeout: str

    :param outpath: path to the directory where both raw and computed results should be stored, defaults to data
    :type outpath: str, optional 
    
    :param delay: Amount of time in seconds to wait between requests, defaults to 0
    :type delay: float
    """
    def __init__(self, takeout=None, outpath='data', delay=0):
        self.takeout = Path(takeout).expanduser()
        self.path = Path(outpath)
        self.delay = delay
        self.raw = os.path.join(self.path, 'raw')  # TODO use Path
        self.ran = os.path.join(self.path, 'ran')  # TODO use Path
        self.df = None
        self.tags = None
        self.grapher = None

        self.seconds = None
        self.formatted_time = None
        self.most_viewed = None
        self.least_viewed = None
        self.best_per_decile = None
        self.worst_per_decile = None
        self.emojis = None
        self.oldest_videos = None
        self.oldest_upload = None
        self.HD = None
        self.UHD = None
        self.top_uploaders = None
        self.most_played_artist = None
        self.most_played_artist_id = None
        self.most_played_uploader_watchtime = None
        self.funny = None
        self.funny_counts = None

    def download_data(self):
        """Loops through takeout data and downloads a json data file for each entry using youtube-dl
    
        """
        watch_history = self.takeout / 'YouTube and YouTube Music/history/watch-history.html'
        if not watch_history.is_file():
            raise ValueError(f'"{watch_history}" is not a file. Did you download your YouTube data? ')
        print('Extracting video urls from Takeout.'); sys.stdout.flush()
        try:
            text = watch_history.read_text()
        except UnicodeDecodeError:
            text = watch_history.read_text(encoding='utf-8')
        else: #if we get to this block just omit the entry
            pass
        soup = BeautifulSoup(text, 'html.parser')
        urls = [u.get('href') for u in soup.find_all('a')]
        videos = [u for u in urls if 'www.youtube.com/watch' in u]
        url_path = self.path / 'urls.txt'
        url_path.write_text('\n'.join(videos))
        print(f'Urls extracted. Downloading data for {len(videos)} videos now.')
        output = os.path.join(self.raw, '%(autonumber)s')
        full_path = os.path.join(os.getcwd(), output)
        try:
            # NEED THE ./ BEFORE THE COMMAND ON MAC
            # cmd = f'./youtube-dl -o "{full_path}" --skip-download --write-info-json -i -a {url_path}'
            # windows exe line
            cmd = f'youtube-dl -o "{full_path}" --skip-download --write-info-json -i -a {url_path}'
        except Exception as e:
            print(f"Data download error: {e}")
        try: 
            p = sp.Popen(cmd, stdout=sp.PIPE, stderr=sp.STDOUT, shell=True)
        except sp.CalledProcessError as e:
            print(f"Popen subprocess error: {e}\n")
            print(f"CalledProcessError return code: {sp.CalledProcessError.returncode}")
        line = True
        while line:
            line = p.stdout.readline().decode("utf-8").strip()
            print(line)

    def deprecated_download_data_via_youtube_dl_login(self):
        """
        Uses users google credentials to download individual json files for each video.
        """
        result = input(DEPRECATION_NOTE)
        if result.lower() != 'y':
            sys.exit()
        print('Okay, Let\'s login and download some data.')
        successful_login = False
        while not successful_login:
            successful_login = True
            user = input('Google username: ')
            pw = getpass.getpass('Google password: ')
            files = os.path.join(self.raw, '%(autonumber)s')
            if not os.path.exists(self.raw):
                os.makedirs(self.raw)
            template = ('youtube-dl -u "{}" -p "{}" '
                        '-o "{}" --sleep-interval {} '
                        '--skip-download --write-info-json -i '
                        'https://www.youtube.com/feed/history ')
            fake = template.format(user, '[$PASSWORD]', files, self.delay)
            print(f'Executing youtube-dl command:\n\n{fake}\n')
            cmd = template.format(user, pw, files, self.delay)
            p = sp.Popen(cmd, stdout=sp.PIPE, stderr=sp.STDOUT, shell=True)
            while True:
                line = p.stdout.readline().decode("utf-8").strip()
                print(line)
                if line == 'WARNING: unable to log in: bad username or password':
                    successful_login = False
                if not line:
                    break

    def df_from_files(self):
        """
        Constructs a Dataframe from the downloaded json files and saves it in the ran data folder 
        for use if the progarm is run again. 
        """
        print('Creating dataframe...')
        num = len([name for name in os.listdir(self.raw) if not name[0] == '.'])
        files = os.path.join(self.raw, '~.info.json') # This is a weird hack
        files = files.replace('~', '{:05d}') # It allows path joining to work on Windows
        data = [json.load(open(files.format(i))) for i in range(1, num + 1)]

        columns = ['formats', 'tags', 'categories', 'thumbnails']
        lists = [[], [], [], []]
        deletes = {k: v for k, v in zip(columns, lists)}
        for dt in data:
            for col, ls in deletes.items():
                ls.append(dt[col])
                del dt[col]

        self.df = pd.DataFrame(data)
        self.df['upload_date'] = pd.to_datetime(self.df['upload_date'], format='%Y%m%d')
        self.df.to_csv(os.path.join(self.ran, 'df.csv'))

        self.tags = deletes['tags']
        pickle.dump(self.tags, open(os.path.join(self.ran, 'tags.txt'), 'wb'))

    def make_wordcloud(self):
        """
        Generates a wordcloud and then sves it as an image for display in the browser.
        """
        print('Creating wordcloud')
        wordcloud = WordCloud(width=1920,
                              height=1080,
                              relative_scaling=.5)
        flat_tags = flatten_without_nones(self.tags)
        wordcloud.generate(' '.join(flat_tags))
        wordcloud.to_file(os.path.join('static', 'images', 'wordcloud.png'))

    def check_df(self):
        """
        Check to see if a dataframe from a previous run exists, if so read from it 
        if not then make a new dataframe
        """
        if not os.path.exists(self.ran):
            os.makedirs(self.ran)
        df_file = os.path.join(self.ran, 'df.csv')
        if os.path.isfile(df_file):
            self.df = pd.read_csv(df_file, index_col=0, parse_dates=[-11])
            self.tags = pickle.load(open(os.path.join(self.ran, 'tags.txt'), 'rb'))
            self.df['upload_date'] = pd.to_datetime(self.df['upload_date'])
        else:
            self.df_from_files()

    def total_time(self):
        """
        Calculte The amount of time spent watching videos.
        """
        self.seconds = self.df.duration.sum()
        seconds = self.seconds
        intervals = (
            ('years', 31449600),  # 60 * 60 * 24 * 7 * 52
            ('weeks', 604800),    # 60 * 60 * 24 * 7
            ('days', 86400),      # 60 * 60 * 24
            ('hours', 3600),      # 60 * 60
            ('minutes', 60),
            ('seconds', 1)
            )
        result = []
        for name, count in intervals:
            value = seconds // count
            if value:
                seconds -= value * count
                if value == 1:
                    name = name.rstrip('s')
                result.append("{} {}".format(int(value), name))
        self.formatted_time = ', '.join(result)

    def top_viewed(self):
        """
        Finds videos with less than 100 views then splits the data set into 
        10 equal sized groups and gets the videos with the highest and lowest view count per 
        group.
        """
        self.most_viewed = self.df.loc[self.df['view_count'].idxmax()]
        # less than 100 views 
        low_views = self.df[self.df['view_count'] < 100] 
        self.least_viewed = low_views.sample(min(len(low_views), 10), random_state=0)
        self.df['deciles'] = pd.qcut(self.df['view_count'], 10, labels=False)
        grouped = self.df.groupby(by='deciles')
        self.worst_per_decile = self.df.iloc[grouped['like_count'].idxmin()]
        self.best_per_decile = self.df.iloc[grouped['like_count'].idxmax()]

    def most_emojis_description(self):
        """
        Find the video description with the most emojis in it.
        """
        def _emoji_variety(desc):
            # getting errors here because some descriptions are NaN or numbers so just skip over any TypeErrors
            try:
                return len({x['emoji'] for x in emoji_lis(desc)})
            except TypeError:
                pass
        counts = self.df['description'].apply(_emoji_variety)
        self.emojis = self.df.iloc[counts.idxmax()]

    def funniest_description(self):
        """
        Counts number of times 'funny' is in each description and saves top result.
        """
        funny_counts = []
        descriptions = []
        index = []
        for i, d in enumerate(self.df.description):
            try:
                funny_counts.append(d.lower().count('funny'))
                descriptions.append(d)
                index.append(i)
            except AttributeError:
                pass
        funny_counts = np.array(funny_counts)
        funny_counts_idx = funny_counts.argmax()
        self.funny_counts = funny_counts[funny_counts_idx]
        if self.funny_counts > 0:
            self.funny = self.df.iloc[index[funny_counts_idx]]
        else:
            title = 'You dont like funny videos?'
            self.funny = make_fake_series(title, release_year_graph='N/A')

    def random_section(self):
        """
        Finds the number of HD and UHD videos watched, 
        the top uploader that you watched, 
        the most played artist, 
        and the description with the "funniest" description
        """
        height = self.df['height'].astype(int)
        self.HD = self.df[(720 <= height) & (height <= 1080)].shape[0]
        self.UHD = self.df[height > 1080].shape[0]
        self.most_played_artist = self.df['uploader'].mode()
        self.funniest_description()
        
    def get_top_uploaders(self):
        channels_id_series = self.df.channel_id.value_counts().head(n=15)
        print(channels_id_series)
        channels_id_arr = []
        top_uploaders = []
        for channel_id, occurrence_count in channels_id_series.items():
            channels_id_arr.append(channel_id)
        joined_string = ",".join(channels_id_arr)
        request = youtube.channels().list(
            part="snippet",
            id=joined_string
        )
        # Request execution
        response = request.execute()
        for key, val in response.items():
            if key == "items":
                for item in val:
                    uploader_id = item["id"]
                    uploader = item["snippet"]["title"]
                    image_url = item["snippet"]["thumbnails"]["medium"]["url"]
                    count = channels_id_series.get(uploader_id)
                    top_uploader = Uploader(uploader, uploader_id, image_url, count)
                    top_uploaders.append(top_uploader)
                    
        sorted_uploaders = sorted(top_uploaders, key=lambda x: x.count, reverse=True)
        
        self.top_uploaders = sorted_uploaders
                    
        
    def calc_most_played_uploader_watchtime(self):
        """Compute the total watchtime for the most played artist"""
        """get a boolean dataframe to determine the indices of the videos by the most played uploader"""
        result_df = self.df['uploader'].isin(self.most_played_artist)
        """Initialize array to store the indices of the videos by the most played uploader"""
        most_played_indices_arr = []
        """Populate the array with the correct indices"""
        for ind in result_df.index:
            if result_df[ind] == True:
                most_played_indices_arr.append(ind)
            
        """Generate a pruned dataframe with only the videos by the most played uploader"""
        pruned_df = self.df.iloc[most_played_indices_arr]
        
        seconds = pruned_df.duration.sum()
        
        intervals = (
            ('years', 31449600),  # 60 * 60 * 24 * 7 * 52
            ('weeks', 604800),    # 60 * 60 * 24 * 7
            ('days', 86400),      # 60 * 60 * 24
            ('hours', 3600),      # 60 * 60
            ('minutes', 60),
            ('seconds', 1)
            )

        result = []

        for name, count in intervals:
            value = seconds // count
            if value:
                seconds -= value * count
                if value == 1:
                    name = name.rstrip('s')
                result.append("{} {}".format(int(value), name))
        self.most_played_uploader_watchtime = ', '.join(result)
        
    def compute(self):
        """
        Computes total time, 
        most liked videos, 
        most emojis in description, 
        10 oldest videos
        oldest upload date
        and the three randoms function 
        """
        print('Computing...')
        self.total_time()
        self.top_viewed()
        self.most_emojis_description()
        self.oldest_videos = self.df[['title', 'webpage_url']].tail(n=10)
        self.oldest_upload = self.df.loc[self.df['upload_date'].idxmin()]
        self.random_section()
        self.get_top_uploaders()
        #self.get_images()
        self.calc_most_played_uploader_watchtime()

    def graph(self):
        """
        Creates a grapher object and runs all graphing functions
        """
        self.grapher = Grapher(self.df, self.tags)
        self.grapher.release_year_graph()
        self.grapher.duration()
        self.grapher.views()
        self.grapher.gen_tags_plot()

    def start_analysis(self):
        """
        Begins the analysis of the data thats been downloaded
        """
        self.check_df()
        if WordCloud is not None:
            self.make_wordcloud()
        self.compute()
        self.graph()

    def run(self):
        """
        Checks if there is data from a previous run, if not downloads the data
        if there is start the analysis immediately
        """
        file1 = os.path.join(self.raw, '00001.info.json')
        some_data = os.path.isfile(file1)
        if not some_data:
            if self.takeout is not None:
                self.download_data()
            else:
                self.deprecated_download_data_via_youtube_dl_login()
        some_data = os.path.isfile(file1)
        if some_data:
            self.start_analysis()
        else:
            print('No data was downloaded.')


if __name__ == '__main__':
    print('Welcome!'); sys.stdout.flush()
    parser = argparse.ArgumentParser()
    parser.add_argument("-o", '--out', default='data',
                        help="Path to empty directory for data storage.")
    parser.add_argument('-d', '--delay', default=0,
                        help='Time to wait between requests. May help avoid 2FA.')
    parser.add_argument('-t', '--takeout',
                        help='Path to an unzipped Takeout folder downloaded from https://takeout.google.com/')
    args = parser.parse_args()
    while (args.takeout == None): 
        print('No takeout file detected, enter path to takeout file')
        args.takeout = input()
        if os.path.exists(args.takeout):
            analysis = Analysis(args.takeout, args.out, float(args.delay))
            analysis.run()
            launch_web()
        else: 
            print('Not a valid file path')
            args.takeout = None
    analysis = Analysis(args.takeout, args.out, float(args.delay))
    analysis.run()
    launch_web()
