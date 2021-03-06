import sys
import argparse
import logging
import praw
import time
from praw.objects import Submission
import re

from ffn_bot.commentlist import CommentList
from ffn_bot.commentparser import formulate_reply, parse_context_markers
from ffn_bot.commentparser import get_direct_links
from ffn_bot.commentparser import StoryLimitExceeded
from ffn_bot import reddit_markdown
from ffn_bot import bot_tools

# For pretty text
from ffn_bot.bot_tools import Fore, Back, Style

__author__ = 'tusing, MikroMan, StuxSoftware'

USER_AGENT = "Python:FanfictionComment:v1.1.2 (by tusing, StuxSoftware, and MikroMan)"
USER_NAME = ""

r = praw.Reddit(USER_AGENT)
DEFAULT_SUBREDDITS = ['HPFanfiction','WormFanfic','NarutoFanfiction','Fanfiction','fandomnatural','marvelfans']
SUBREDDIT_LIST = set()
CHECKED_COMMENTS = None
FOOTER = "\n".join([
    r"**FanfictionBot**^(1.4.0) **|** \[[Usage][1]\] | \[[Changelog][2]\] | \[[Issues][3]\] | \[[GitHub][4]\] | \[[Contact][5]\]",
    r'[1]: https://github.com/tusing/reddit-ffn-bot/wiki/Usage       "How to use the bot"',
    r'[2]: https://github.com/tusing/reddit-ffn-bot/wiki/Changelog   "What changed until now"',
    r'[3]: https://github.com/tusing/reddit-ffn-bot/issues/          "Bugs? Suggestions? Enter them here!"',
    r'[4]: https://github.com/tusing/reddit-ffn-bot/                 "Fork me on GitHub"',
    r'[5]: https://www.reddit.com/message/compose?to=tusing          "The maintainer"'
])
FOOTER += "\n\n^^^^^^^^^^^^^^^^^ffnbot!ignore"
FOOTER += "\n\n^(*New in this version: Slim recommendations using* ffnbot!slim! *Thread recommendations using* linksub(thread_id)^)!"

# For testing purposes
DRY_RUN = False

# This is a experimental feature of the program
# Please use with caution
USE_STREAMS = False

def run_forever():
    sys.exit(_run_forever())


def _run_forever():
    """Run-Forever"""
    while True:
        try:
            main()
        # Exit on sys.exit and keyboard interrupts.
        except KeyboardInterrupt:
            raise
        except SystemExit as e:
            return e.code
        except:
            logging.error("MAIN: AN EXCEPTION HAS OCCURED!")
            bot_tools.print_exception()
            bot_tools.pause(0, 30)
        finally:
            if CHECKED_COMMENTS is not None:
                CHECKED_COMMENTS.save()


def main():
    """Basic main function."""
    # moved call for agruments to avoid double calling
    global bot_parameters
    bot_parameters = get_bot_parameters()
    login_to_reddit(bot_parameters)
    load_subreddits(bot_parameters)
    init_global_flags(bot_parameters)

    # Messaging Framework
    global COUNT_REPLIES 
    global COUNT_REPLIES_LIMIT 
    global TIME_TO_RESET 
    global TIME_SINCE_RESET 
    COUNT_REPLIES = {}  # Count replies per user
    COUNT_REPLIES_LIMIT= 30  # How many requests we'll allow per TIME_TO_RESET
    TIME_TO_RESET = 86400  # Time until we reset this dictionary (in seconds)
    TIME_SINCE_RESET = time.time()  # Time since the last dictionary reset


    if USE_STREAMS:
        print("========================================")
        print("Stream Based, Will not gracefully restart.")
        stream_strategy()
        sys.exit()

    while True:
        single_pass()


def init_global_flags(bot_parameters):
    global USE_GET_COMMENTS, DRY_RUN, CHECKED_COMMENTS, USE_STREAMS

    if bot_parameters["experimental"]["streams"]:
        print("You are using the stream approach.")
        print("Please note that the application will not propely")
        print("restart on creashes due to limitations of the")
        print("Python threading interface.")
        USE_STREAMS = True

    DRY_RUN = bool(bot_parameters["dry"])
    if DRY_RUN:
        print("Dry run enabled. No comment will be sent.")

    CHECKED_COMMENTS = CommentList(bot_parameters["comments"], DRY_RUN)

    level = getattr(logging, bot_parameters["verbosity"].upper())
    logging.getLogger().setLevel(level)


def get_bot_parameters():
    """Parse the command-line arguments."""
    # initialize parser and add options for username and password
    parser = argparse.ArgumentParser()
    parser.add_argument('-u', '--user',
                        help='define Reddit login username')
    parser.add_argument(
        '-p', '--password',
        help='define Reddit login password')

    parser.add_argument(
        '-s', '--subreddits',
        help='define target subreddits; seperate with commas')

    parser.add_argument(
        '-d', '--default',
        action='store_true',
        help='add default subreddits, can be in addition to -s')

    parser.add_argument(
        '-c', '--comments',
        help="Filename where comments are stored",
        default="CHECKED_COMMENTS.txt")

    parser.add_argument(
        '-l', '--dry',
        action='store_true',
        help="do not send comments.")

    parser.add_argument(
        "--streams",
        action="store_true",
        help="Highly experimental feature. Handle posts as they come")

    parser.add_argument(
        "-v", "--verbosity",
        default="INFO",
        help="The default log level. Using python level states.")

    args = parser.parse_args()

    return {
        'user': args.user,
        'password': args.password,
        'user_subreddits': args.subreddits,
        'default': args.default,
        'dry': args.dry,
        'comments': args.comments,
        'verbosity': args.verbosity,
        # Switches for experimental features
        'experimental': {
            "streams": args.streams
        }
    }


def login_to_reddit(bot_parameters):
    """Performs the login for reddit."""
    global USER_NAME
    USER_NAME = bot_parameters['user']
    print("Logging in...")
    r.login(bot_parameters['user'], bot_parameters['password'])
    print(Fore.GREEN, "Logged in.", Style.RESET_ALL)



def load_subreddits(bot_parameters):
    """Loads the subreddits this bot operates on."""
    global SUBREDDIT_LIST
    print("Loading subreddits...")

    if bot_parameters['default'] is True:
        print("Adding default subreddits: ", DEFAULT_SUBREDDITS)
        for subreddit in DEFAULT_SUBREDDITS:
            SUBREDDIT_LIST.add(subreddit)

    if bot_parameters['user_subreddits'] is not None:
        user_subreddits = bot_parameters['user_subreddits'].split(',')
        print("Adding user subreddits: ", user_subreddits)
        for subreddit in user_subreddits:
            SUBREDDIT_LIST.add(subreddit)

    if len(SUBREDDIT_LIST) == 0:
        print("No subreddit specified. Adding test subreddit.")
        SUBREDDIT_LIST.add('tusingtestfield')
    print("LOADED SUBREDDITS: ", SUBREDDIT_LIST)


def handle_submission(submission, markers=frozenset()):
    if (not is_submission_checked(submission)) and (not "ignore" in markers) or ("force" in markers):
        logging.info("Found new submission: " + submission.id)
        try:
            parse_submission_text(submission, markers)
        finally:
            check_submission(submission)


def handle_message(message):
    global COUNT_REPLIES, TIME_SINCE_RESET, TIME_TO_RESET, COUNT_REPLIES_LIMIT
    """What we're using to handle direct messages."""
    # Mark message as read here so we don't loop over it in case of error.
    message.mark_as_read()

    # Check for message validity.
    if not valid_comment(message):
        logging.error("Received invalid message...")
        return
    try:
        if message.submission is not None:
            logging.info("Parsing message belonging to a submission!")
            return
    except AttributeError:
        pass

    # If enough time has elapsed, reset COUNT_REPLIES to an empty dict.
    if time.time() - TIME_SINCE_RESET >= TIME_TO_RESET:
        COUNT_REPLIES = {}

    # Count the number of requests in the body of the message, of format link...(...;...;...)
    request_count = message.body.count('link') + message.body.count(';')
    body = message.body

    markers = set()
    sub_recs = None
    if 'linksub(' in body:
        sub_recs = get_sub_reccomendations(body)
        markers.add('slim')

    # If the message author can not be found in the dict, add them.
    COUNT_REPLIES.setdefault(message.author.name, request_count)

    # Print a summary of the user's statistics.
    logging.info("{0} has requested {1} fics with {2} remaining requests for the next {3} seconds.".format(
        message.author.name, request_count, COUNT_REPLIES_LIMIT - COUNT_REPLIES[message.author.name], 
        TIME_TO_RESET - (time.time() - TIME_SINCE_RESET)))

    # Block the request if the user has exceeded their quota of replies.
    if COUNT_REPLIES[message.author.name] + request_count > COUNT_REPLIES_LIMIT:
        logging.error("{0} has exceeded their available replies.", message.author.name)
        return

    # Otherwise, add the number of requests to the user's total number of requests.
    COUNT_REPLIES[message.author.name] += request_count

    # Print the current state of COUNT_REPLIES.
    logging.info("The current state of DM requests: {0}", COUNT_REPLIES)

    # Make the reply and return.
    make_reply(body, message.id, message.reply, markers=markers, sub_recs=sub_recs)
    return


def handle_comment(comment, extra_markers=frozenset()):
    logging.debug("Handling comment: " + comment.id)
    if (str(comment.id) not in CHECKED_COMMENTS
            ) or ("force" in extra_markers):

        markers = parse_context_markers(comment.body)
        markers |= extra_markers
        if "ignore" in markers:
            # logging.info("Comment forcefully ignored: " + comment.id)
            return
        else:
            logging.info("Found new comment: " + comment.id)

        if "parent" in markers:
            if comment.is_root:
                item = comment.submission
            else:
                item = r.get_info(thing_id=comment.parent_id)
            handle(item, {"directlinks", "submissionlink", "force"})

        if "delete" in markers and (comment.id not in CHECKED_COMMENTS):
            CHECKED_COMMENTS.add(str(comment.id))
            logging.info("Delete requested by " + comment.id)
            if not (comment.is_root):
                parent_comment = r.get_info(thing_id=comment.parent_id)
                if parent_comment.author is not None:
                    if (parent_comment.author.name == bot_parameters['user']):
                        logging.info("Deleting comment " + parent_comment.id)
                        parent_comment.delete()
                    else:
                        logging.error("Delete requested on non-bot comment!")
                else:
                    logging.error("Delete requested on null comment.")
            else:
                logging.error("Delete requested by invalid comment!")

        if "refresh" in markers and (str(comment.id) not in CHECKED_COMMENTS):
            CHECKED_COMMENTS.add(str(comment.id))
            logging.info("(Refresh) Refresh requested by " + comment.id)

            # Get the full comment or submission
            comment_with_requests = get_full(comment.parent_id)
            logging.info("(Refresh) Refreshing on " + type(
                comment_with_requests).__name__ + " with id " + comment_with_requests.id)

            # TODO: Make it so FanfictionBot does not have to be hardcoded
            # If ffnbot!refresh is called on an actual bot reply, then go up
            # one level to find the requesting comment

            if not valid_comment(comment_with_requests):
                logging.error(
                    "(Refresh) Comment with requests is invalid.")
                return

            if comment_with_requests.author.name == bot_parameters['user']:
                logging.info(
                    "(Refresh) Refresh requested on a bot comment (" + comment_with_requests.id + ").")
                # Retrieve the requesting parent submission or comment
                comment_with_requests = get_full(
                    comment_with_requests.parent_id)

                # If the requesting comment has been deleted, abort
                if not valid_comment(comment_with_requests):
                    logging.error(
                        "(Refresh) Parent of bot comment is invalid.")
                    return

                logging.info(
                    "          Refresh request being pushed to parent " + comment_with_requests.id)

            if isinstance(comment_with_requests, praw.objects.Comment):
                logging.info(
                    "(Refresh) Running refresh on COMMENT " + str(comment_with_requests.id))
                logging.info("(Refresh) Appending replies to deletion check list: " +
                             ", ".join(str(c.id) for c in comment_with_requests.replies))
                delete_list = comment_with_requests.replies

            elif isinstance(comment_with_requests, praw.objects.Submission):
                logging.info(
                    "(Refresh) Running refresh on SUBMISSION " + str(comment_with_requests.id))

                unfiltered_delete_list = comment_with_requests.comments
                delete_list = []
                for comment in unfiltered_delete_list:
                    if comment.author is not None:
                        if (comment.author.name == bot_parameters['user']):
                            delete_list.append(comment)
                            print(
                                "(Refresh) Found root-level bot comment " + comment.id)
            else:
                logging.error("(Refresh) Can't refresh " + comment_with_requests.type(
                ).__name__ + " with ID " + comment_with_requests.id)
                bot_tools.pause(5, 0)
                return

            if delete_list is not None:
                logging.info("(Refresh) Finding replies to delete.")
                for reply in delete_list:
                    if valid_comment(reply):
                        if (reply.author.name == bot_parameters['user']):
                            logging.error(
                                "(Refresh) Deleting bot comment " + reply.id)
                            reply.delete()
            else:
                logging.info(
                    "(Refresh) No bot replies have been made. Continuing...")
            CHECKED_COMMENTS.add(str(comment.id))

            if isinstance(comment_with_requests, praw.objects.Comment):
                logging.info(
                    "(Refresh) Re-handling comment " + comment_with_requests.id)
                handle_comment(comment_with_requests, frozenset(["force"]))
            elif isinstance(comment_with_requests, praw.objects.Submission):
                logging.info(
                    "(Refresh) Re-handling submission " + comment_with_requests.id)
                handle_submission(comment_with_requests, frozenset(["force"]))
            return

        body = comment.body
        sub_recs = None
        if 'linksub(' in body:
            sub_recs = get_sub_reccomendations(body)
            markers.add('slim')
        
        try:
            make_reply(body, comment.id, comment.reply, markers, sub_recs=sub_recs)
        finally:
            CHECKED_COMMENTS.add(str(comment.id))


def get_full(comment_id):
    """
    Will return a full comment or submission.
    Very heavy on time.
    """
    requested_comment = r.get_info(thing_id=comment_id)
    if isinstance(requested_comment, praw.objects.Comment):
        # PRAW doesn't return replies in a comment object retrieved with
        # get_info; we must do this:
        requested_comment = r.get_submission(
            requested_comment.permalink).comments[0]
    elif isinstance(requested_comment, praw.objects.Submission):
        requested_comment = r.get_submission(requested_comment.permalink)
        requested_comment.replace_more_comments(limit=None, threshold=0)
    else:
        logging.error(
            "(URGENT) WAS NOT ABLE TO DETERMINE COMMENT VS SUBMISSION!")
        requested_comment = r.get_submission(requested_comment.permalink)
    return requested_comment


def get_sub_reccomendations(request_body):
    """
    Recommend multiple submissions, using linksub(...)
    Output: A slim-ified version of bot reccommendations in the requested threads.
    """
    sub_ids = [] # A list of all requested submission IDs.

    # Capture everything inside linksub(...)
    sub_requests = re.findall('linksub\((.*)\)', request_body)

    for sub_request in sub_requests: # For every linksub(...),
        # Add the submission ID for every Reddit thread linked, and
        sub_ids += re.findall('redd\.it\/(\S{6})', sub_request)
        sub_ids += re.findall('\/comments\/(\S{6})', sub_request)
        # Add the submission ID if it is explicitly defined.
        sub_request = sub_request.replace(" ", "") # Remove whitespace
        sub_ids += [sub_id for sub_id in sub_request.split(';') if len(sub_id)==6]

    logging.info("(SUBMISSION REQUEST) Handling the following submission IDs: " + " ".join(sub_ids))
    replies = [] # A list of bot replies.

    def single_sub_recommendations(sub_id): # Get the full text for one submission
        # Get the submission's subreddit. It must be a subreddit the bot runs on.
        submission = r.get_submission(submission_id=sub_id, comment_limit=None, comment_sort='top')
        subreddit_name = r.get_info(thing_id=submission.subreddit.name).display_name
        if subreddit_name.upper() in [subreddit.upper() for subreddit in SUBREDDIT_LIST]:
            # Return a list of all bot comments in this submission.
            return [comment.body for comment in praw.helpers.flatten_tree(submission.comments) 
                    if valid_comment(comment) and comment.author.name == USER_NAME]
        else:
            logging.error("(SUBMISSION REQUEST) Received request to parse invalid submission in /r/" + subreddit_name)
            logging.error("                     Current valid subreddits are " + " ".join(SUBREDDIT_LIST))
            return ""

    # We build replies[] by calling single_sub_reccomendations on every requested submission.
    for sub_id in sub_ids:
        try:
            reply = single_sub_recommendations(sub_id)
            replies.append("\n ".join(reply))
            logging.info("(SUBMISSION REQUEST) Handled submission ID: " + sub_id)
        except Exception as e:
            logging.error("(SUBMISSIONR RECS) Failed to get sub reccommendations for sub_id " + sub_id)
            logging.error(e)

    all_recommended_stories = []
    for bot_comment in replies:
        if 'p0ody-files' in bot_comment: # Download site moved to new domain.
            bot_comment = bot_comment.replace('p0ody-files', 'ff2ebook')
            bot_comment = bot_comment.replace('ff_to_ebook', 'old')
        all_recommended_stories += slimify_comment(bot_comment)
    return all_recommended_stories


def slimify_comment(bot_comment):
    """
    Slims down a bot comment into essential information: fic name, author, and description.
    Returns a list of stories.
    TODO: Find a less hacky way to do this.
    """
    find_key = lambda slim_story: re.findall('(\[(\ |\S)+\) by)', slim_story)[0][0]
    if 'slim!FanfictionBot' in bot_comment:
        slimmed_stories = [story[0] for story in re.findall('((\n(.+)by(.+)(\s|\S)+?)\n+\>(\ |\S)+\n)', bot_comment)]
        slimmed_stories_dict = {}
        for story in slimmed_stories:
            try:
                slimmed_stories_dict[find_key(story)] = story
            except:
                pass
        slimmed_stories = slimmed_stories_dict
    else:
        all_metadata = re.findall('(\^(\s|\S)*?\-{3})', bot_comment) # Get metadata
        num_stories = len(all_metadata)
        titles_authors = re.findall('((\n(.+)by(.+))\n+\>)', bot_comment)
        titles_authors = [title_author[1] for title_author in titles_authors]
        summaries = re.findall('(\>(.*))\n+\^', bot_comment)
        summaries = [summary[0] for summary in summaries]
        wordcounts = re.findall('(Word(\D)+((\d{1,3})+(,|\d{1,3})+)+)', str(all_metadata))
        wordcounts = [wordcount[2] for wordcount in wordcounts]
        downloads = [re.findall('(\*Download\*(\s|\S)+\-{3})', str(story_metadata)) for story_metadata in all_metadata]
        downloads_fixed = [] # Not all sites have downloads. We'll take care of this:
        for download in downloads:
            try:
                downloads_fixed.append(download[0][0])
            except:
                downloads_fixed.append("No download available)")

        slimmed_stories = {}
        for i in range(len(all_metadata)):
            complete = ''
            if str(all_metadata[i]).__contains__('*Status*: Complete'):
                complete = ', complete'
            story = '\n\n' + titles_authors[i]
            story += ' (' + wordcounts[i] + ' words' + complete + '; ' + downloads_fixed[i]
            story += '\n\n' + summaries[i] + '\n\n'
            story = story.replace('\\n', '\n')
            story = story.replace('---', '')
            try:
                slimmed_stories.update({find_key(story): story})
            except:
                pass
    return list(slimmed_stories.values())






def valid_comment(comment):
    """
    Checks if valid comment.
    """
    if comment.author is None:
        logging.error("Found invalid comment " + comment.id)
        return False
    return True


def handle(obj, markers=frozenset()):
    if isinstance(obj, Submission):
        handle_submission(obj, markers)
    else:
        handle_comment(obj, markers)


def stream_handler(queue, iterator, handler):

    def _raise(exc):
        raise exc

    try:
        for post in iterator:
            print("Queueing Post:", post.id)
            queue.put_nowait((handler, post))
    except BaseException as e:
        # Send the actual exception to the main thread
        queue.put_nowait((_raise, e))


def post_receiver(queue):
    while True:
        handler, post = queue.get()
        handler(post)


def stream_strategy():
    from queue import Queue
    from threading import Thread
    from praw.helpers import submission_stream, comment_stream

    post_queue = Queue()

    threads = []
    threads.append(Thread(target=lambda: stream_handler(
        post_queue,
        comment_stream(
            r,
            "+".join(SUBREDDIT_LIST),
            limit=100,
            verbosity=0
        ),
        handle_comment
    )))
    threads.append(Thread(target=lambda: stream_handler(
        post_queue,
        submission_stream(
            r,
            "+".join(SUBREDDIT_LIST),
            limit=100,
            verbosity=0
        ),
        handle_submission
    )))

    for thread in threads:
        thread.daemon = True
        thread.start()

    while True:
        try:
            post_receiver(post_queue)
        except Exception as e:
            for thread in threads:
                if not thread.isAlive():
                    raise KeyboardInterrupt from e
            bot_tools.print_exception(e)


def single_pass():
    try:
        # We actually use a multireddit to acieve our goal
        # of watching multiple reddits.
        subreddit = r.get_subreddit("+".join(SUBREDDIT_LIST))

        logging.info("Parsing new submissions.")
        for submission in subreddit.get_new(limit=50):
            handle_submission(submission)

        logging.info("Parsing new comments.")
        for comment in subreddit.get_comments(limit=100):
            handle_comment(comment)

        logging.info("Parsing unread messages.")
        for message in r.get_unread():
            handle_message(message)

    except Exception:
        bot_tools.print_exception()
    bot_tools.pause(0, 15)


def check_submission(submission):
    """Mark the submission as checked."""
    global CHECKED_COMMENTS
    CHECKED_COMMENTS.add("SUBMISSION_" + str(submission.id))


def is_submission_checked(submission):
    """Check if the submission was checked."""
    global CHECKED_COMMENTS
    return "SUBMISSION_" + str(submission.id) in CHECKED_COMMENTS




def parse_submission_text(submission, extra_markers=frozenset()):
    body = submission.selftext

    markers = parse_context_markers(body)
    markers |= extra_markers

    # Since the bot would start downloading the stories
    # here, we add the ignore option here
    if "ignore" in markers:
        return

    additions = []
    if "submissionlink" in markers:
        additions.extend(get_direct_links(submission.url, markers))

    sub_recs = None
    if 'linksub(' in body:
        sub_recs = get_sub_reccomendations(body)
        markers.add('slim')

    make_reply(
        body, submission.id, submission.add_comment,
        markers, additions, sub_recs=sub_recs)


def make_reply(body, id, reply_func, markers=None, additions=(), sub_recs=None):
    """Makes a reply for the given comment."""
    try:
        reply = list(formulate_reply(body, markers, additions))
    except StoryLimitExceeded:
        if not DRY_RUN:
            reply_func("You requested too many fics.\n"
                       "\nWe allow a maximum of 30 stories")
        bot_tools.print_exception(level=logging.DEBUG)
        print("Too many fics...")
        return

    raw_reply = "".join(reply)
    if 'slim' not in markers and len(raw_reply) > 10:
        print("Writing reply to", id, "(", len(raw_reply), "characters in",
              len(reply), "messages)")
        # Do not send the comment.
        if not DRY_RUN:
            for part in reply:
                reply_func(part + FOOTER)
    if 'slim' in markers and (len(raw_reply) > 10 or sum([len(rec) for rec in sub_recs]) > 10):
        # This is CRITICAL until we find a cleaner way to do this. slim!FanfictionBot is to be used
        # when parsing threads that already have slim stories.
        slim_footer = "\n\n---\n\n*slim!FanfictionBot*^(1.4.0)."
        slim_stories = []
        # Submission recs (if they exist) are already slimmed.
        if sub_recs is not None:
            slim_stories += sub_recs
            slim_footer += " Note that some story data has been sourced from older threads, and may be out of date."
        slim_stories += slimify_comment(raw_reply)

        # Deal with any remaining duplicates.
        find_key = lambda slim_story: re.findall('(\[(\ |\S)+\) by)', slim_story)[0][0]
        slim_stories = list({find_key(story): story for story in slim_stories}.values())

        total_character_count = sum([len(story) for story in slim_stories])
        print("Writing a slim reply to", id, "(", total_character_count, "characters in about",
              total_character_count/(10000-len(slim_footer)), "messages)")

        current_reply = []
        while len(slim_stories) is not 0: # We use slim_stories as a queue.
            current_story = slim_stories.pop(0)
            # Comments can be up to 10,000 characters:
            if sum([len(story) for story in current_reply]) + len(current_story) > 10000 - len(slim_footer):
                reply_func("".join(current_reply) + slim_footer)
                bot_tools.pause(0, 10)
                current_reply = []
            else:
                current_reply += current_story
        if len(current_reply) is not 0:
               reply_func("".join(current_reply) + slim_footer)
    else:
        logging.info("No reply conditions met.")    

    bot_tools.pause(0, 15)
    print('Continuing to parse submissions...')
 
