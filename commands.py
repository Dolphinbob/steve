import json
import os
import sys
from uuid import UUID
import random
import re
import slack
from flask import Flask, abort, jsonify, request
from mcstatus import MinecraftServer
from mcuuid.api import GetPlayerData
import requests

# get configs
slackVerifyToken = os.environ['TOKEN']
slackTeamId = os.environ['TEAM_ID']
slackBotToken = os.environ['BOT_OAUTH_TOKEN']
playerDataApi = os.environ['PLAYER_DATA_API']
censoredWords = os.environ['CENSORED_WORDS']


slack_client = slack.WebClient(
    token=slackBotToken
)


def getPlayerUUID(username):
    """Return as a "long" UUID"""
    data = GetPlayerData(username)
    return UUID(data.uuid)


def getNick(uuid):
    try:
        with open(f'players/{uuid}.json') as f:
            # Gathers nick from HCCore's JSON file
            nick = json.load(f)['nickname']
            print('User\'s file was found! Sending.')
            nick = re.sub(censoredWords, 'null', nick)
            return nick
    except FileNotFoundError:
        print(f'User {uuid} not found! Getting their json file.')
        res = requests.get(f'{playerDataApi}/{uuid}.json')
        open(f'players/{uuid}.json', 'wb').write(res.content)
        nick = re.sub(censoredWords, 'null', res.json()['nickname'])
        return nick


def getFormattedOutput(reName, realName):
    """Gets the formatted output of the username, complete with nickname support
    - Places a "\u200c" character after nickname
      -  prevent slack from tagging someone by name
      - still show name without visible modification"""
    uuid = getPlayerUUID(realName)

    try:
        nick = getNick(uuid)

        ign = '\u200c'.join(reName[i:i+1]
                            for i in range(0, len(reName), 1))
        if nick == None:  # if the Nick doesn't exist, return just the username
            output = f'- {ign}'
        else:
            output = '- ' + \
                '\u200c'.join(
                    nick[i:i+1] for i in range(0, len(nick), 1)) + f' ({ign})'
    except TypeError as e:
        f'- {ign}'
        print(f'ERROR: {e}')

    if '[BOT]' in nick:
        output = f'~{output}~'

    output += '\n'

    return output


def buildStatusMessage(config):
    """Builds the final message to send to slack
    - Header (# Players online)
    - Nicknames + IGNs of online players"""
    try:
        server = MinecraftServer.lookup(config['address'])
        status = server.status()
    except ConnectionRefusedError:
        return f"*{config['name']}:* Server is down! :scream:"

    if status.players.online == 0:
        return f"*{config['name']}:* No players online :disappointed:"

    """Fun addition - if there are 4 players online,
    there is a 20% chance that the appearing emoji will
    be :weed:. Can be disabled in config."""
    emote = ':bust_in_silhouette:'
    try:
        if status.players.online == 4 and config['weedEasterEgg'] != False:
            randomNum = random.randint(0, 4)
            if randomNum == 4:
                emote = ':weed:'
    except KeyError:
        pass

    message = (f"*{config['name']}:* " + str(status.players.online) +
               ' out of ' + str(status.players.max) + f' {emote} online:\n')

    for player in status.players.sample:
        name = re.sub(censoredWords, 'null', player.name)
        message += getFormattedOutput(reName=name, realName=player.name)

    return message


def buildFullMessage(channel, user):
    message = []

    with open('servers.json') as f:
        servers = json.load(f)
        for server in servers:
            message.extend([
                {
                    'type': 'section',
                    'text': {
                        'type': 'mrkdwn',
                        'text': buildStatusMessage(server)
                    }
                },
                {
                    'type': 'divider'
                },
                {
                    "type": "actions",
                    "elements": [
                            {
                                "type": "button",
                                "text": {
                                        "type": "plain_text",
                                        "text": "Delete",
                                        "emoji": True
                                },
                                "style": "danger"
                            }
                    ]
                },
                {
                    'type': 'context',
                    'elements': [
                        {
                            'type': 'mrkdwn',
                            'text': f'Requested by <@{user}>'
                        }
                    ]
                }

            ])

    # Remove the divider after the last section
    if len(message) > 1:
        del message[-3]

    return message


app = Flask(__name__)


def request_valid(request):  # checks for valid slack token / ID
    """Checks whether or not the request from slack is valid"""
    token_valid = request.form['token'] == slackVerifyToken
    team_id_valid = request.form['team_id'] == slackTeamId
    return token_valid and team_id_valid


def postRichChatMessage(channel, blocks):
    # Posts public JSON-formatted slack message
    slack_client.chat_postMessage(
        token=slackBotToken,
        channel=channel,
        as_user=True,
        blocks=blocks
    )


def postPlainChatMessage(channel, text):
    # Posts public plaintext slack message
    slack_client.chat_postMessage(
        token=slackBotToken,
        channel=channel,
        as_user=True,
        text=text
    )


def postEphemeralMessage(channel, text, user):
    # Posts ephemeral plaintext slack message
    slack_client.chat_postEphemeral(
        token=slackBotToken,
        channel=channel,
        as_user=True,
        text=text,
        user=user
    )


def delChatMessage(channel, ts):
    # Delete chat message based on ts
    slack_client.chat_delete(
        token=slackBotToken,
        channel=channel,
        as_user=True,
        ts=ts
    )


def joinChannel(channel):
    # Method to add the bot to a public channel
    slack_client.conversations_join(
        token=slackBotToken,
        channel=channel
    )


@app.route('/players', methods=['POST'])  # checking for POST from slack
def players():

    # If verification fails, return 400
    if not request_valid(request):
        print('Request invalid!')
        abort(400)

    channel = request.form['channel_id']
    user = request.form['user_id']

    msg = buildFullMessage(channel, user)

    try:  # Attempts to post message in channel
        postRichChatMessage(channel=channel, blocks=msg)
    except:
        try:  # If it cannot post in the channel, it will attempt to join the channel
            joinChannel(
                channel=channel)
            postRichChatMessage(channel=channel, blocks=msg)
        except:  # If it cannot join the channel, it will DM the command runner
            postRichChatMessage(
                channel=user,
                blocks=msg
            )
            postPlainChatMessage(
                channel=user,
                text=f'In order to use the bot in the channel, please invite <@UKD6P483E>!')

    # Returns 200 to make slack happy and avoid operation_timeout
    return ('', 200)


@app.route('/delete', methods=['POST'])
def delete():
    """Deletes messages posted by the bot"""

    # Grabs and parses payload from button
    payload = json.loads(request.form.to_dict()['payload'])

    # Parses original message sender from message - slack decided to up the number of caracters in their UIDs, and I didn't feel like writing regex for this.
    origMessageSignature = payload['message']['blocks'][2]['elements'][0]['text']
    if len(origMessageSignature) == 25:
        origMessageSender = origMessageSignature[15:24]
    elif len(origMessageSignature) == 27:
        origMessageSender = origMessageSignature[15:26]

    deleteReqSender = payload['user']['id']

    channel = payload['channel']['id']
    ts = payload['message']['ts']

    # Only allows original message sender or me to delete message
    if deleteReqSender == origMessageSender or deleteReqSender == 'UE8DH0UHM':  # yes ik
        delChatMessage(
            channel=channel,
            ts=ts
        )
    else:
        print(
            f'Delete sender is {deleteReqSender}, orig is {origMessageSender}.')
        postEphemeralMessage(
            channel=channel,
            user=deleteReqSender,
            text=f'Sorry, you can\'t do that!'
        )

    return jsonify(
        # Tells slack that the original message was deleted
        delete_original=True
    )
