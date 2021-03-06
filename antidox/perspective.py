""" inputs comments to perspective and dlp apis and detects
toxicity and personal information> has support for csv files,
bigquery tables, and wikipedia talk pages"""
#TODO(tamajongnc): configure pipeline to distribute work to multiple machines
# pylint: disable=fixme, import-error
# pylint: disable=fixme, unused-import
import argparse
import json
import sys
from googleapiclient import discovery
from googleapiclient import errors as google_api_errors
import pandas as pd
import requests
import apache_beam as beam
from apache_beam.io.gcp.internal.clients import bigquery
from apache_beam.options.pipeline_options import PipelineOptions
from apache_beam.options.pipeline_options import SetupOptions
from apache_beam.options.pipeline_options import GoogleCloudOptions
from apache_beam.options.pipeline_options import StandardOptions
from apache_beam.options.pipeline_options import WorkerOptions
from apache_beam import window
from antidox import clean

def get_client():
  """ generates API client with personalized API key """
  with open("api_key.json") as json_file:
    apikey_data = json.load(json_file)
  api_key = apikey_data['perspective_key']
  # Generates API client object dynamically based on service name and version.
  perspective = discovery.build('commentanalyzer', 'v1alpha1',
                                developerKey=api_key)
  dlp = discovery.build('dlp', 'v2', developerKey=api_key)
  return (apikey_data, perspective, dlp)


def perspective_request(perspective, comment):
  """ Generates a request to run the toxicity report"""
  analyze_request = {
      'comment':{'text': comment},
      'requestedAttributes': {'TOXICITY': {}, 'THREAT': {}, 'INSULT': {}}
  }
  response = perspective.comments().analyze(body=analyze_request).execute()
  return response

def dlp_request(dlp, apikey_data, comment):
  """ Generates a request to run the cloud dlp report"""
  request_dlp = {
      "item":{
          "value":comment
          },
      "inspectConfig":{
          "infoTypes":[
              {
                  "name":"PHONE_NUMBER"
              },
              {
                  "name":"US_TOLLFREE_PHONE_NUMBER"
              },
              {
                  "name":"DATE_OF_BIRTH"
              },
              {
                  "name":"EMAIL_ADDRESS"
              },
              {
                  "name":"CREDIT_CARD_NUMBER"
              },
              {
                  "name":"IP_ADDRESS"
              },
              {
                  "name":"LOCATION"
              },
              {
                  "name":"PASSPORT"
              },
              {
                  "name":"PERSON_NAME"
              },
              {
                  "name":"ALL_BASIC"
              }
              ],
          "minLikelihood":"POSSIBLE",
          "limits":{
              "maxFindingsPerItem":0
              },
          "includeQuote":True
          }
      }
  dlp_response = (dlp.projects().content().inspect(body=request_dlp,
                                                   parent='projects/'+
                                                   apikey_data['project_number']
                                                   ).execute())
  return dlp_response


def contains_pii(dlp_response):
  """ Checking/returning comments that are likely or very likely to contain PII

      Args:
      passes in the resukts from the cloud DLP
      """
  has_pii = False
  if 'findings' not in dlp_response['result']:
    return False, None
  for finding in dlp_response['result']['findings']:
    if finding['likelihood'] in ('LIKELY', 'VERY_LIKELY'):
      has_pii = True
      return (has_pii, finding['infoType']["name"])
  return False, None


def contains_toxicity(perspective_response):
  """Checking/returning comments with a toxicity value of over 50 percent."""
  is_toxic = False
  if (perspective_response['attributeScores']['TOXICITY']['summaryScore']
      ['value'] >= .5):
    is_toxic = True
  return is_toxic


def get_wikipage(pagename):
  """ Gets all content from a wikipedia page and turns it into plain text. """
  # pylint: disable=fixme, line-too-long
  page = ("https://en.wikipedia.org/w/api.php?action=query&prop=revisions&rvprop=content&format=json&formatversion=2&titles="+(pagename))
  get_page = requests.get(page)
  response = json.loads(get_page.content)
  text_response = response['query']['pages'][0]['revisions'][0]['content']
  return text_response


def wiki_clean(get_wikipage):
  """cleans the comments from wikipedia pages"""
  text = clean.content_clean(get_wikipage)
  print(text)
  return text


def use_query(content, sql_query, big_q):
  """make big query api request"""
  query_job = big_q.query(sql_query)
  rows = query_job.result()
  strlst = []
  for row in rows:
    strlst.append(row[content])
  return strlst

def set_pipeline_options(options):
  gcloud_options = options.view_as(GoogleCloudOptions)
  gcloud_options.project = 'google.com:new-project-242016'
  gcloud_options.staging_location = 'gs://tj_cloud_bucket/stage'
  gcloud_options.temp_location = 'gs://tj_cloud_bucket/tmp'
  options.view_as(StandardOptions).runner = 'direct'
  options.view_as(WorkerOptions).num_workers = 69
  options.view_as(SetupOptions).save_main_session = True

# pylint: disable=fixme, too-many-locals
# pylint: disable=fixme, too-many-statements
def main(argv):
  """ runs dlp and perspective on content passed in """
  parser = argparse.ArgumentParser(description='Process some integers.')
  parser.add_argument('--input_file', help='Location of file to process')
  parser.add_argument('--api_key', help='Location of perspective api key')
  # pylint: disable=fixme, line-too-long
  parser.add_argument('--sql_query', help='choose specifications for query search')
  parser.add_argument('--csv_file', help='choose CSV file to process')
  parser.add_argument('--wiki_pagename', help='insert the talk page name')
  parser.add_argument('--content', help='specify a column in dataset to retreive data from')
  parser.add_argument('--output', help='path for output file in cloud bucket')
  parser.add_argument('--nd_output', help='gcs path to store ndjson results')
  parser.add_argument('--project', help='project id for bigquery table', \
                                   default='wikidetox-viz')
  parser.add_argument('--gproject', help='gcp project id')
  parser.add_argument('--temp_location', help='cloud storage path for temp files \
                                              must begin with gs://')
  args, pipe_args = parser.parse_known_args(argv)
  options = PipelineOptions(pipe_args)
  set_pipeline_options(options)
  with beam.Pipeline(options=options) as pipeline:
    if args.wiki_pagename:
      wiki_response = get_wikipage(args.wiki_pagename)
      wikitext = wiki_clean(wiki_response)
      text = wikitext.split("\n")
      comments = pipeline | beam.Create(text)
    if args.csv_file:
      comments = pipeline | 'ReadMyFile' >> beam.io.ReadFromText(pd.read_csv(args.csv_file))
    if args.sql_query:
      comments = (
          pipeline
          | 'QueryTable' >> beam.io.Read(beam.io.BigQuerySource(
              query=args.sql_query,
              use_standard_sql=True))
          | beam.Map(lambda elem: elem[args.content]))

    # pylint: disable=fixme, too-few-public-methods
    class NDjson(beam.DoFn):
      """class for NDJson"""

      # pylint: disable=fixme, no-self-use
      # pylint: disable=fixme, inconsistent-return-statements
      def process(self, element):
        """Takes toxicity and dlp results and converst them to NDjson"""
        try:
          dlp_response = dlp_request(dlp, apikey_data, element)
          perspective_response = perspective_request(perspective, element)
          contains_toxicity(perspective_response)
          has_pii_bool, pii_type = contains_pii(dlp_response)
          if contains_toxicity(perspective_response) or has_pii_bool:
            data = {'comment': element,
                    'Toxicity': str(perspective_response['attributeScores']
                                    ['TOXICITY']['summaryScore']['value']),
                    'pii_detected':str(pii_type)}
            return [json.dumps(data) + '\n']
        except google_api_errors.HttpError as err:
          print('error', err)

    # pylint: disable=fixme, too-few-public-methods
    class GetToxicity(beam.DoFn):
      """The DoFn to perform on each element in the input PCollection"""

      # pylint: disable=fixme, no-self-use
      # pylint: disable=fixme, inconsistent-return-statements
      def process(self, element):
        """Runs every element of collection through perspective and dlp"""
        print(repr(element))
        print('==============================================\n')
        if not element:
          return None
        try:
          dlp_response = dlp_request(dlp, apikey_data, element)
          perspective_response = perspective_request(perspective, element)
          has_pii_bool, pii_type = contains_pii(dlp_response)
          if contains_toxicity or has_pii_bool:
            pii = [element+"\n"+'contains pii?'+"Yes"+"\n"+str(pii_type)+"\n" \
                  +"\n" +"contains TOXICITY?:"+"Yes"
                   +"\n"+str(perspective_response['attributeScores']
                             ['TOXICITY']['summaryScore']['value'])+"\n"
                   +"=========================================="+"\n"]
            return pii 
        except google_api_errors.HttpError as err:
          print('error', err)
    apikey_data, perspective, dlp = get_client()
    results = comments \
     | beam.ParDo(GetToxicity())
    json_results = comments \
     | beam.ParDo(NDjson())
    # pylint: disable=fixme, expression-not-assigned
    results | 'WriteToText' >> beam.io.WriteToText(
        'gs://tj_cloud_bucket/beam.txt', num_shards=1)
    json_results | 'WriteToText2' >> beam.io.WriteToText(
        'gs://tj_cloud_bucket/results.json', num_shards=1)
if __name__ == '__main__':
  main(sys.argv[1:])