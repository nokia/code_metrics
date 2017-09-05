import ConfigParser
import json
import logging
import os.path
import re
from datetime import datetime
from datetime import timedelta

import pandas as pd
from pygerrit.client import GerritClient

logging.basicConfig(format='%(asctime)s %(levelname)s %(message)s',
                    level=logging.INFO)


class GerritLogParser(object):
    """Get data from Gerrit and generate metrics
    """

    def __init__(self):
        """ Read options' value from config file
        """
        logging.info("Start to init GerritLogParser...")
        self.config = ConfigParser.RawConfigParser()
        self.config.read(os.path.join(os.path.abspath(os.path.dirname(__file__))) + os.sep + 'config')

        self.re_subject = {}
        for (column, regex) in self.config.items("SubjectRegex"):
            self.re_subject[column] = re.compile(regex)

        self.re_common = {}
        for (column, regex) in self.config.items("CommonRegex"):
            self.re_common[column] = re.compile(regex)

        self.gerrit_client = GerritClient(self.config.get("GerritServer", "host"),
                                          self.config.get("GerritServer", "username"),
                                          self.config.getint("GerritServer", "port"))
        self.time_format = "%Y-%m-%d %H:%M:%S"
        self.TA_FILE_KEY = 'robot'

        self.init_raw_data()

    def _init_columns(self, metric_type):
        self.mandatory_columns = self.config.get(metric_type, 'mandatory_columns').lower().replace(' ', '').split(',')
        self.optional_columns = self.config.get(metric_type, 'optional_columns').lower().replace(' ', '').split(',')
        self.columns = self.mandatory_columns + self.optional_columns
        self._filter_owner_comments = self.config.getboolean(metric_type,'filter_owner_comments')

    def get_query_command(self):
        """ Get query search operators from config.new and compose them to query command
        :arg:
            metric_type: str, query search operators configured in config
        :return: query command
            eg: query --format=JSON --patch-sets --current-patch-set --files --comments project:netact/radio3 status:merged
        """
        exec_dtime = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        command = "query --format=JSON --patch-sets --current-patch-set --files --comments"

        items = self.config.items("GerritQuerySearchOperator")
        search_operators = []
        has_date = False
        for (op_name, op_value) in items:
            if op_name in ["before", "until", "after", "since"]:
                has_date = True
                break

        for (op_name, op_value) in items:
            if op_name in ["before", "until", "after", "since"]:
                search_operators.append("%s:\'\"%s\"\'" % (op_name, op_value))
                continue
            if op_name == "lastdays":
                if not has_date:
                    time_from = exec_dtime - timedelta(days=int(op_value))
                    search_operators.append("%s:\'\"%s\"\'" % ("after", str(time_from)))
                    search_operators.append("%s:\'\"%s\"\'" % ("before", str(exec_dtime)))
                    continue
                else:
                    continue
            search_operators.append("%s:%s" % (op_name, op_value))
        command = "%s %s" % (command, ' '.join(search_operators))
        logging.info("query command: %s " % command)

        return command

    def init_raw_data(self):
        """ Get raw data from Gerrit
        """
        result = self.gerrit_client.run_command(self.get_query_command())
        self._raw_df = pd.DataFrame([json.loads(line) for line in result.stdout.read().splitlines()[:-1]])

    def compute_file_metrics(self):
        """ Compute file metrics, corresponding sections in config are:
            [FileMetrics]
        """
        logging.info("Start to compute file metrics...")
        self._init_columns('FileMetrics')

        df = pd.DataFrame(data=None, columns=None)
        df['id'] = self._raw_df['id']
        df['project'] = self._raw_df['project']
        df['subject'] = self._raw_df['subject']
        df['owner'] = self._raw_df['owner'].apply(lambda x: x.get('username'))
        df['last_updated'] = self._raw_df['lastUpdated'].apply(
            lambda x: datetime.fromtimestamp(float(x)).strftime(self.time_format))

        f_df = self._get_file_comments_df(self._raw_df)
        del f_df['owner']
        f_df = self._filter_files(f_df)
        f_df = pd.merge(f_df, df, on=["id"]).sort_index()
        f_df = f_df.groupby(['project', 'file']).apply(self.compute_file_metrics_for_file_group).reset_index()

        logging.info("Finished to compute file metrics...")
        return f_df

    def compute_file_metrics_for_file_group(self, x):
        result = {}
        owners_set = set()
        for i in x['owner'].get_values():
            owners_set.add(i)

        comments = []
        for i in x['comment'].get_values():
            if i:
                comments.append(i)

        result.update({'modification_times': x['id'].count(),
                       'modification_lines': (x['insertions'] - x['deletions']).sum(),
                       'comments_num': len(comments),
                       'comments': '\n'.join(comments),
                       'owners': '\n'.join(owners_set),
                       'owners_num': len(owners_set)
                       })
        self.compute_optional_file_metrics_for_file_group(x, result)
        return pd.Series(result)

    def compute_optional_file_metrics_for_file_group(self, x, result):
        for column in self.optional_columns:
            if '_num' in column:
                x[column] = x['subject'].apply(lambda y: 1 if self.re_subject.get(column).match(y) else 0)
                result[column] = x[column].sum()
            else:
                x[column] = x['subject'].apply(
                    lambda y: self.re_subject.get(column).match(y).groupdict()[column].replace(":", "")
                    if self.re_subject.get(column).match(y) else "")
                result[column] = '\n'.join(x[column].as_matrix())

    def compute_subject_metrics(self):
        """ Compute subject metrics, corresponding sections in config are:
           [SubjectMetrics]
       """
        logging.info("Start to compute subject metrics...")
        self._init_columns('SubjectMetrics')

        df = pd.DataFrame(data=None, columns=None)
        df['last_updated'] = self._raw_df['lastUpdated'].apply(
            lambda x: datetime.fromtimestamp(float(x)).strftime(self.time_format))
        df['id'] = self._raw_df['id']
        df['number'] = self._raw_df['number']
        df['url'] = self._raw_df['url']
        df['project'] = self._raw_df['project']
        df['subject'] = self._raw_df['subject']
        df['owner'] = self._raw_df['owner'].apply(lambda x: x.get('username'))
        df['change_comments'] = self._raw_df['comments']

        f_df = self._get_file_comments_df(self._raw_df)
        f_df = self._filter_files(f_df)
        f_df = f_df.groupby(['id']).apply(self.compute_subject_metrics_for_file_group).reset_index()

        df = pd.merge(df, f_df, on=["id"]).sort_index()
        del df['id']
        logging.info("Finished to compute subject metrics...")

        return df

    def compute_subject_metrics_for_file_group(self, x):
        insertions = 0
        deletions = 0
        ta_insertions = 0
        ta_deletions = 0
        comments = []
        reviewers = set()

        for (f, owner, ins, dels, reviewer, comment) in x.as_matrix(
                ['file', 'owner', 'insertions', 'deletions', 'reviewer', 'comment']):
            ins = ins if ins != '-' else 0
            dels = dels if dels != '-' else 0

            if comment:
                comments.append("%s : %s" % (reviewer, comment))
                reviewers.add(reviewer)

            if self.TA_FILE_KEY in f:
                ta_insertions = ta_insertions + ins
                ta_deletions = ta_deletions + dels
            insertions = insertions + ins
            deletions = deletions + dels

        x = self._filter_files(x)

        result = {
            'files': '\n'.join(x['file'].values),
            'files_num': x['file'].count(),
            'modification_lines': insertions - deletions,
            'insertions': insertions,
            'deletions': deletions,
            'comments': '\n'.join(comments),
            'comments_num': len(comments),
            'reviewers': '\n'.join(reviewers),
            'reviewers_num': len(reviewers),
            'ta_insertions': ta_insertions,
            'ta_deletions': ta_deletions,
            'ta_modification_lines': ta_insertions - ta_deletions,
        }

        return pd.Series(result)

    def _filter_files(self, df):
        """ Filter files
        :arg:
            df, DataFrame which contains 'file' column
        """
        return df[df['file'].map(lambda x: not self.re_common.get("file_to_filter").match(x))]

    def _get_file_comments_df(self, df):
        """ Get file comments df
        :arg:
            df, DataFrame, raw df parsed from Gerrit output
        :return:
            DataFrame with below columns:
            id, owner, file, insertions, deletions, reviewer, comment
        """

        def get_comments(patch_sets):
            f_comments = []
            for ps in patch_sets:
                if ps.get("comments"):
                    f_comments.extend(ps.get("comments"))
            return f_comments

        t_df = pd.DataFrame(data=None, columns=None)
        t_df['id'] = df['id']
        t_df['owner'] = df['owner'].apply(lambda x: x.get('username'))
        t_df['files'] = df['currentPatchSet'].apply(lambda x: x.get('files'))
        t_df['file_comments'] = df['patchSets'].apply(lambda x: get_comments(x))

        f_df_data = []
        for (change_id, owner, files, file_comments) in t_df[['id', 'owner', 'files', 'file_comments']].values:
            for f in files:
                f_r = {}
                f_name = f.get("file")
                f_r['id'] = change_id
                f_r['owner'] = owner
                f_r['file'] = f_name
                insertions = f.get("insertions") if f.get("insertions") != "-" else 0
                deletions = f.get("deletions") if f.get("deletions") != "-" else 0
                f_r['insertions'] = insertions
                f_r['deletions'] = deletions

                has_comment = False
                if file_comments:
                    for c in file_comments:
                        if f_name == c.get('file'):
                            has_comment = True
                            t = f_r.copy()
                            t['comment'] = c.get("message")
                            t['reviewer'] = c.get("reviewer").get("username")
                            f_df_data.append(t)

                if not has_comment:
                    f_r['reviewer'] = ''
                    f_r['comment'] = ''
                    f_df_data.append(f_r)

        f_c_df = pd.DataFrame(f_df_data)
        f_c_df = f_c_df if not self._filter_owner_comments else f_c_df[f_c_df['owner'] != f_c_df['reviewer']]
        return f_c_df


if __name__ == '__main__':
    gp = GerritLogParser()
    gp.compute_file_metrics().to_csv("file_metrics.csv", encoding='utf-8')
    gp.compute_subject_metrics().to_csv("subject_metrics.csv", encoding='utf-8')
