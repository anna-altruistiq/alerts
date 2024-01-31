import json
import boto3
from datetime import datetime, timedelta
import time
import urllib3
import re

PD_API_URL = "https://events.pagerduty.com/v2/enqueue"
PD_ROUTING_KEYS = {
    "product": "R03E06M6QUDI8IOKHEQFAC95WHQEBWVV",
    "dev": "R03E082DCK7NS1R3IWVEZYY3H9MMPNGT",
    "volcano": "R03E082DWFL7T2CP8NC269Y5349XOK5Q"
    }
PLAYBOOK_LINK = "https://www.notion.so/altruistiq/1ab7675075764753a0208970ea495408?v=b915b2ba8ccc4028816c49e15be90c30"
ERROR_CODE_REGEX = r'^\[\w+\][^[]\[(\w+)\].*$'

def lambda_handler(event, context):

    try:
        print("trying...")
        #parse the message
        message = event.get("Records")[0]
        print("The Message's Records is ", message)

        
        message = message.get("body")
        print("The Message's body is ", message)
        
        message = json.loads(message)
        print("The Message's body is after loads", message)
        
        message = message.get("Message")
        print("The Message's message is ", message)

        message = json.loads(message)
        print("The Message's message is after loads", message)

        #add the alarmTarget field for routing
        alarmTarget = ""
        alarmName = message.get("AlarmName")
        print("The AlarmName is ", alarmName)
        
        errorCode = re.search(ERROR_CODE_REGEX, message.get("AlarmDescription")).group(1)
        print("The errorCode is ", errorCode)
        
        if "APP" in errorCode:
            alarmTarget = "dev"
        elif "DATA_1" in errorCode:
            alarmTarget = "volcano"
        else:
            alarmTarget = "product"
            
        logGroupName = message.get("AlarmDescription").split('Log group: ')[1]
        
        # will have 2 queries, one with error code and one without
        queryStringError = 'fields @message | filter error.error_code like /' + errorCode +'/ | sort @timestamp desc | limit 1'
        queryString = 'fields @message | sort @timestamp desc | limit 1'

        # get logs with the same error code
        client = boto3.client('logs')
        startQueryResponse = client.start_query(
            logGroupName=logGroupName,
            startTime=int((datetime.today() - timedelta(hours=300)).timestamp()),
            endTime=int(datetime.now().timestamp()),
            queryString=queryStringError,
        )
        
        queryID = startQueryResponse['queryId']

        # wait for query to complete
        response = None
        while response == None or response['status'] in ['Running', 'Scheduled']:
            print('Waiting for query to complete ...')
            time.sleep(1)
            response = client.get_query_results(
                queryId=queryID
            )

        results = response["results"]
        print("results = ", results)
        
        # if there are no results, try without error code
        if results == None:
            print("Will try without error code.")
            startQueryResponse = client.start_query(
                logGroupName=logGroupName,
                startTime=int((datetime.today() - timedelta(hours=300)).timestamp()),
                endTime=int(datetime.now().timestamp()),
                queryString=queryString,
            )
            
            queryID = startQueryResponse['queryId']
            
            response = None
            while response == None or response['status'] in ['Running', 'Scheduled']:
                print('Waiting for query to complete ...')
                time.sleep(1)
                response = client.get_query_results(
                    queryId=queryID
                )
    
            
            results = response["results"]
            print("results = ", results)

        # strip out the fields we don't want to present in the alert
        logs = []
        if results != 0:
            print(type(results))
            print("len of results after loads = ", len(results))
            
            # if there are multiple results, glue them together to a list
            for i, result in enumerate(results):
                print("i = ", i)
                print("result = ", result)
                if result[0]['field'] == '@message':
                    logs.append(json.loads(result[0]['value']))
                    print("result[i]['value'] #", i, " = ", result[i]['value'])
                    i += 1
                    
        print("logs = ", logs)
        
        #parsing useful info from the logs
        errorDetails = logs[0]['error']
        print("errorDetails = ", errorDetails)
        
        traceback = "No traceback found."
        context = 'No context found.'
        errorsDetails = 'No details found.'
        
        if 'extra' in logs[0]:
            if 'exc_info' in logs[0]['extra']:
                traceback = logs[0]['extra']['exc_info']
            if ('body' in logs[0]['extra']) and ('context' in logs[0]['extra']['body']):
                context = logs[0]['extra']['body']['context']
            if 'errors' in logs[0]['extra']:
                errorsDetails = logs[0]['extra']['errors']
                
        print("traceback = ", traceback)
        print("context = ", context)
        print("errorsDetails = ", errorsDetails)
        
        custom_details = {
            #   "Name": message.get("AlarmName"),
              "Description": message.get("AlarmDescription"),
              "Timestamp": message.get("AlarmConfigurationUpdatedTimestamp"),
            #   "Log group": logGroupName,
            #   "Alarm target": alarmTarget,
            #   "Error code": errorCode,
              "Error details": errorDetails,
              "Context": context,
              "Traceback": traceback,
              "More details": errorsDetails
            }
        
        payload = {
            "summary": message.get("AlarmDescription"),
            "timestamp": message.get("AlarmConfigurationUpdatedTimestamp"),
            "component": message.get("AlarmName"),
            "source": logGroupName,
            "severity": "error",
            "custom_details": custom_details
        }
        
        links = [
            {
              "href": PLAYBOOK_LINK,
              "text": "Playbooks"
            }
          ]
        
        #send message straight to PD using API v2
        eventPD = {
          "payload": payload,
          "routing_key": PD_ROUTING_KEYS[alarmTarget],
          "dedup_key": "",
          "images": [],
          "links": links,
          "event_action": "trigger"
        }
        
        http = urllib3.PoolManager()
        response = http.request('POST', PD_API_URL,
             headers={'Content-Type': 'application/json'},
             body=json.dumps(eventPD))
        
        print("All good, response = ", response)

        return {
            'StatusCode': 200,
            'Message': 'Successfully executed the function.'
        }
    
    except Exception as e:
        print("Something went wrong, Please Investigate. Error --> ", e)
        
        return {
            'StatusCode': 400,
            'Message': 'Something went wrong, Please Investigate. Error --> '+ str(e)
        }