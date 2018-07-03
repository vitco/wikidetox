"""Tests for spanner_write."""

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function
import unittest
import os
from write_utils.write import SpannerWriter
from google.gax import retry


class SpannerWriteTest(unittest.TestCase):

  def test_spanner_write(self):
    writer = SpannerWriter('wikiconv', 'page_info')
    writer.create_table('page_states', ({'page_id': "STRING", 'authors':"STRING",
                                         'conversation_id': "STRING", 'deleted_comments': "ARRAY(STRING)",
                                         'page_state': "STRING", 'rev_id': "INT", 'timestamp': "TIMESTAMP"}))
    try:
      ret = writer.insert_data('page_states', {'page_id': 'test_page_id', 'authors': 'test_authors',
                                               'conversation_id': 'test_conversation_id',
                                               'deleted_comments': ['test_deleted_comment1', 'test_deleted_comment2'],
                                               'page_state': 'test_page_state',
                                               'rev_id': 123,
                                               'timestamp': '2018-06-29T00:00:00Z'})
    except Exception as e:
      if 'StatusCode.ALREADY_EXISTS' in str(e):
        ret = 'Inserted data.'
        pass
      else:
        raise Exception(e)
    self.assertEqual(ret, 'Inserted data.')
    try:
      ret = writer.insert_data('page_states', {'page_id': 'test_page_id', 'authors': 'test_authors',
                                               'conversation_id': 'test_conversation_id',
                                               'deleted_comments': ['test_deleted_comment1', 'test_deleted_comment2'],
                                               'page_state': 'test_page_state',
                                               'rev_id': 124,
                                               'timestamp': '2018-06-29T00:00:00Z'})
    except Exception as e:
      if 'StatusCode.ALREADY_EXISTS' in str(e):
        ret = 'Inserted data.'
        pass
      else:
        raise Exception(e)
    self.assertEqual(ret, 'Inserted data.')
    # Test BigQuery Input
    cmd = os.system("python dataflow_main.py --bigquery_table=scored_conversations.spanner_import_test_case\
                    --spanner_instance=wikiconv --spanner_database=convdata --spanner_table=convdata\
                    --spanner_table_columns_config=config --testmode --setup_file=./setup.py")
    exit_code = os.WEXITSTATUS(cmd)
    self.assertEqual(exit_code, 0)


if __name__ == '__main__':
  unittest.main()
