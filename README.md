## Code metrics
A python library which compute metrics for Gerrit changes.

## Requirements
python2.7, pygerrit, pandas.

## Usage
**GerritLogParser.py** : It queries Gerrit for change logs, and compute metrics, eg: file metrics, subject metrics.

    if __name__ == '__main__':
        gp = GerritLogParser()
        gp.compute_file_metrics().to_csv("file_metrics.csv", encoding='utf-8')
        gp.compute_subject_metrics().to_csv("subject_metrics.csv", encoding='utf-8')

**Config** : Configuration file read by GerritLogParser.py. Take file metrics for example:
* [GerritServer]: Gerrit server info

      [GerritServer]
      host = xxx
      port = xxx
      username = xxx

* [GerritQuerySearchOperator] : Gerrit query search operators. You can refer to [documentation](https://review.openstack.org/Documentation/user-search.html).

      [FileGerritQuerySearchOperator]
      parentproject = xxx
      status = merged
      branch = master
      before = 2017-09-05 00:00:00
      after = 2017-08-29 00:00:00

* [FileMetrics] :

    mandatory_columns : Metric columns which are calculated by default.

    optional_columns : Metric columns which are caculated from 'subject' value. Each item has corresponding regex in [SubjectRegex]. It can be configured.

      [FileMetrics]
      mandatory_columns = project, file, modification_times, modification_lines, owners_num, owners, comments_num, comments
      optional_columns = fc_us_num, fc_us_title, jr_num, jr_title, iwi_num, iwi_title, pr_num, pr_title

* [SubjectRegex] : It can be modified based on subject format.

      [SubjectRegex]
      fc_us_num = %(TBC|FIN|WIP|DONE) (FC|US):
      jr_num = %(TBC|FIN|WIP|DONE) JR:
      iwi_num = %(TBC|FIN|WIP|DONE) IWI:
      ...


## License

This project is licensed under the BSD-3-Clause license - see the [LICENSE](https://github.com/nokia/code_metrics/blob/master/LICENSE).