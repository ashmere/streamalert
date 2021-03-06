"""Alert on any Duo authentication logs marked as a failure due to an Anonymous IP."""
from stream_alert.rule_processor.rules_engine import StreamRules

rule = StreamRules.rule


@rule(logs=['duo:authentication'],
      outputs=['aws-s3:sample-bucket',
               'pagerduty:sample-integration',
               'slack:sample-channel'])
def duo_anonymous_ip_failure(rec):
    """
    author:       airbnb_csirt
    description:  Alert on any Duo authentication logs marked as a failure due to an Anonymous IP.
    reference:    N/A
    playbook:     N/A
    """
    return rec['result'] == 'FAILURE' and rec['reason'] == 'Anonymous IP'
