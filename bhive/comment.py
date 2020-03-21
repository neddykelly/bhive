# This Python file uses the following encoding: utf-8
from __future__ import absolute_import
from __future__ import division
from __future__ import print_function
from __future__ import unicode_literals
from builtins import str
import json
import re
import logging
import pytz
import math
from datetime import datetime, date, time
from .instance import shared_hive_instance
from .account import Account
from .amount import Amount
from .price import Price
from .utils import resolve_authorperm, construct_authorperm, derive_permlink, remove_from_dict, make_patch, formatTimeString, formatToTimeStamp
from .blockchainobject import BlockchainObject
from .exceptions import ContentDoesNotExistsException, VotingInvalidOnArchivedPost
from bhivebase import operations
from bhivegraphenebase.py23 import py23_bytes, bytes_types, integer_types, string_types, text_type
from bhive.constants import HIVE_REVERSE_AUCTION_WINDOW_SECONDS_HF6, HIVE_REVERSE_AUCTION_WINDOW_SECONDS_HF20, HIVE_100_PERCENT, HIVE_1_PERCENT, HIVE_REVERSE_AUCTION_WINDOW_SECONDS_HF21
log = logging.getLogger(__name__)


class Comment(BlockchainObject):
    """ Read data about a Comment/Post in the chain

        :param str authorperm: identifier to post/comment in the form of
            ``@author/permlink``
        :param boolean use_tags_api: when set to False, list_comments from the database_api is used
        :param Hive hive_instance: :class:`bhive.hive.Hive` instance to use when accessing a RPC


        .. code-block:: python

        >>> from bhive.comment import Comment
        >>> from bhive.account import Account
        >>> from bhive import Hive
        >>> hv = Hive()
        >>> acc = Account("gtg", hive_instance=hv)
        >>> authorperm = acc.get_blog(limit=1)[0]["authorperm"]
        >>> c = Comment(authorperm)
        >>> postdate = c["created"]
        >>> postdate_str = c.json()["created"]

    """
    type_id = 8

    def __init__(
        self,
        authorperm,
        use_tags_api=True,
        full=True,
        lazy=False,
        hive_instance=None
    ):
        self.full = full
        self.lazy = lazy
        self.use_tags_api = use_tags_api
        self.hive = hive_instance or shared_hive_instance()
        if isinstance(authorperm, string_types) and authorperm != "":
            [author, permlink] = resolve_authorperm(authorperm)
            self["id"] = 0
            self["author"] = author
            self["permlink"] = permlink
            self["authorperm"] = authorperm
        elif isinstance(authorperm, dict) and "author" in authorperm and "permlink" in authorperm:
            authorperm["authorperm"] = construct_authorperm(authorperm["author"], authorperm["permlink"])
            authorperm = self._parse_json_data(authorperm)
        super(Comment, self).__init__(
            authorperm,
            id_item="authorperm",
            lazy=lazy,
            full=full,
            hive_instance=hive_instance
        )

    def _parse_json_data(self, comment):
        parse_times = [
            "active", "cashout_time", "created", "last_payout", "last_update",
            "max_cashout_time"
        ]
        for p in parse_times:
            if p in comment and isinstance(comment.get(p), string_types):
                comment[p] = formatTimeString(comment.get(p, "1970-01-01T00:00:00"))
        # Parse Amounts
        hbd_amounts = [
            "total_payout_value",
            "max_accepted_payout",
            "pending_payout_value",
            "curator_payout_value",
            "total_pending_payout_value",
            "promoted",
        ]
        for p in hbd_amounts:
            if p in comment and isinstance(comment.get(p), (string_types, list, dict)):
                comment[p] = Amount(comment.get(p, "0.000 %s" % (self.hive.hbd_symbol)), hive_instance=self.hive)

        # turn json_metadata into python dict
        meta_str = comment.get("json_metadata", "{}")
        if meta_str == "{}":
            comment['json_metadata'] = meta_str
        if isinstance(meta_str, (string_types, bytes_types, bytearray)):
            try:
                comment['json_metadata'] = json.loads(meta_str)
            except:
                comment['json_metadata'] = {}

        comment["tags"] = []
        comment['community'] = ''
        if isinstance(comment['json_metadata'], dict):
            if "tags" in comment['json_metadata']:
                comment["tags"] = comment['json_metadata']["tags"]
            if 'community' in comment['json_metadata']:
                comment['community'] = comment['json_metadata']['community']

        parse_int = [
            "author_reputation",
        ]
        for p in parse_int:
            if p in comment and isinstance(comment.get(p), string_types):
                comment[p] = int(comment.get(p, "0"))

        if "active_votes" in comment:
            new_active_votes = []
            for vote in comment["active_votes"]:
                if 'time' in vote and isinstance(vote.get('time'), string_types):
                    vote['time'] = formatTimeString(vote.get('time', "1970-01-01T00:00:00"))
                parse_int = [
                    "rshares", "reputation",
                ]
                for p in parse_int:
                    if p in vote and isinstance(vote.get(p), string_types):
                        try:
                            vote[p] = int(vote.get(p, "0"))
                        except:
                            vote[p] = int(0)
                new_active_votes.append(vote)
            comment["active_votes"] = new_active_votes
        return comment

    def refresh(self):
        if self.identifier == "":
            return
        if not self.hive.is_connected():
            return
        [author, permlink] = resolve_authorperm(self.identifier)
        self.hive.rpc.set_next_node_on_empty_reply(True)
        if self.hive.rpc.get_use_appbase():
            try:
                if self.use_tags_api:
                    content = self.hive.rpc.get_discussion({'author': author, 'permlink': permlink}, api="tags")
                else:
                    content =self.hive.rpc.list_comments({"start": [author, permlink], "limit": 1, "order": "by_permlink"}, api="database")
                if content is not None and "comments" in content:
                    content =content["comments"]
                if isinstance(content, list) and len(content) >0:
                    content =content[0]
            except:
                content = self.hive.rpc.get_content(author, permlink)
        else:
            content = self.hive.rpc.get_content(author, permlink)
        if not content or not content['author'] or not content['permlink']:
            raise ContentDoesNotExistsException(self.identifier)
        content = self._parse_json_data(content)
        content["authorperm"] = construct_authorperm(content['author'], content['permlink'])
        super(Comment, self).__init__(content, id_item="authorperm", lazy=self.lazy, full=self.full, hive_instance=self.hive)

    def json(self):
        output = self.copy()
        if "authorperm" in output:
            output.pop("authorperm")
        if 'json_metadata' in output:
            output["json_metadata"] = json.dumps(output["json_metadata"], separators=[',', ':'])
        if "tags" in output:
            output.pop("tags")
        if "community" in output:
            output.pop("community")
        parse_times = [
            "active", "cashout_time", "created", "last_payout", "last_update",
            "max_cashout_time"
        ]
        for p in parse_times:
            if p in output:
                p_date = output.get(p, datetime(1970, 1, 1, 0, 0))
                if isinstance(p_date, (datetime, date)):
                    output[p] = formatTimeString(p_date)
                else:
                    output[p] = p_date
        hbd_amounts = [
            "total_payout_value",
            "max_accepted_payout",
            "pending_payout_value",
            "curator_payout_value",
            "total_pending_payout_value",
            "promoted",
        ]
        for p in hbd_amounts:
            if p in output and isinstance(output[p], Amount):
                output[p] = output[p].json()
        parse_int = [
            "author_reputation",
        ]
        for p in parse_int:
            if p in output and isinstance(output[p], integer_types):
                output[p] = str(output[p])
        if "active_votes" in output:
            new_active_votes = []
            for vote in output["active_votes"]:
                if 'time' in vote:
                    p_date = vote.get('time', datetime(1970, 1, 1, 0, 0))
                    if isinstance(p_date, (datetime, date)):
                        vote['time'] = formatTimeString(p_date)
                    else:
                        vote['time'] = p_date
                parse_int = [
                    "rshares", "reputation",
                ]
                for p in parse_int:
                    if p in vote and isinstance(vote[p], integer_types):
                        vote[p] = str(vote[p])
                new_active_votes.append(vote)
            output["active_votes"] = new_active_votes
        return json.loads(str(json.dumps(output)))

    @property
    def id(self):
        return self["id"]

    @property
    def author(self):
        return self["author"]

    @property
    def permlink(self):
        return self["permlink"]

    @property
    def authorperm(self):
        return construct_authorperm(self["author"], self["permlink"])

    @property
    def category(self):
        if "category" in self:
            return self["category"]
        else:
            return ""

    @property
    def parent_author(self):
        return self["parent_author"]

    @property
    def parent_permlink(self):
        return self["parent_permlink"]

    @property
    def depth(self):
        return self["depth"]

    @property
    def title(self):
        if "title" in self:
            return self["title"]
        else:
            return ""

    @property
    def body(self):
        if "body" in self:
            return self["body"]
        else:
            return ""

    @property
    def json_metadata(self):
        if "json_metadata" in self:
            return self["json_metadata"]
        else:
            return {}

    def is_main_post(self):
        """ Returns True if main post, and False if this is a comment (reply).
        """
        if 'depth' in self:
            return self['depth'] == 0
        else:
            return self["parent_author"] == ''

    def is_comment(self):
        """ Returns True if post is a comment
        """
        if 'depth' in self:
            return self['depth'] > 0
        else:
            return self["parent_author"] != ''

    @property
    def reward(self):
        """ Return the estimated total HBD reward.
        """
        a_zero = Amount(0, self.hive.hbd_symbol, hive_instance=self.hive)
        author = Amount(self.get("total_payout_value", a_zero), hive_instance=self.hive)
        curator = Amount(self.get("curator_payout_value", a_zero), hive_instance=self.hive)
        pending = Amount(self.get("pending_payout_value", a_zero), hive_instance=self.hive)
        return author + curator + pending

    def is_pending(self):
        """ Returns if the payout is pending (the post/comment
            is younger than 7 days)
        """
        a_zero = Amount(0, self.hive.hbd_symbol, hive_instance=self.hive)
        total = Amount(self.get("total_payout_value", a_zero), hive_instance=self.hive)
        post_age_days = self.time_elapsed().total_seconds() / 60 / 60 / 24
        return post_age_days < 7.0 and float(total) == 0

    def time_elapsed(self):
        """Returns a timedelta on how old the post is.
        """
        utc = pytz.timezone('UTC')
        return utc.localize(datetime.utcnow()) - self['created']

    def curation_penalty_compensation_HBD(self):
        """ Returns The required post payout amount after 15 minutes
            which will compentsate the curation penalty, if voting earlier than 15 minutes
        """
        self.refresh()
        if self.hive.hardfork >= 21:
            reverse_auction_window_seconds = HIVE_REVERSE_AUCTION_WINDOW_SECONDS_HF21
        elif self.hive.hardfork >= 20:
            reverse_auction_window_seconds = HIVE_REVERSE_AUCTION_WINDOW_SECONDS_HF20
        else:
            reverse_auction_window_seconds = HIVE_REVERSE_AUCTION_WINDOW_SECONDS_HF6
        return self.reward * reverse_auction_window_seconds / ((self.time_elapsed()).total_seconds() / 60) ** 2

    def estimate_curation_HBD(self, vote_value_HBD, estimated_value_HBD=None):
        """ Estimates curation reward

            :param float vote_value_HBD: The vote value in HBD for which the curation
                should be calculated
            :param float estimated_value_HBD: When set, this value is used for calculate
                the curation. When not set, the current post value is used.
        """
        self.refresh()
        if estimated_value_HBD is None:
            estimated_value_HBD = float(self.reward)
        t = 1.0 - self.get_curation_penalty()
        k = vote_value_HBD / (vote_value_HBD + float(self.reward))
        K = (1 - math.sqrt(1 - k)) / 4 / k
        return K * vote_value_HBD * t * math.sqrt(estimated_value_HBD)

    def get_curation_penalty(self, vote_time=None):
        """ If post is less than 15 minutes old, it will incur a curation
            reward penalty.

            :param datetime vote_time: A vote time can be given and the curation
                penalty is calculated regarding the given time (default is None)
                When set to None, the current date is used.
            :returns: Float number between 0 and 1 (0.0 -> no penalty, 1.0 -> 100 % curation penalty)
            :rtype: float

        """
        if vote_time is None:
            elapsed_seconds = self.time_elapsed().total_seconds()
        elif isinstance(vote_time, str):
            elapsed_seconds = (formatTimeString(vote_time) - self["created"]).total_seconds()
        elif isinstance(vote_time, (datetime, date)):
            elapsed_seconds = (vote_time - self["created"]).total_seconds()
        else:
            raise ValueError("vote_time must be a string or a datetime")
        if self.hive.hardfork >= 21:
            reward = (elapsed_seconds / HIVE_REVERSE_AUCTION_WINDOW_SECONDS_HF21)
        elif self.hive.hardfork >= 20:
            reward = (elapsed_seconds / HIVE_REVERSE_AUCTION_WINDOW_SECONDS_HF20)
        else:
            reward = (elapsed_seconds / HIVE_REVERSE_AUCTION_WINDOW_SECONDS_HF6)
        if reward > 1:
            reward = 1.0
        return 1.0 - reward

    def get_vote_with_curation(self, voter=None, raw_data=False, pending_payout_value=None):
        """ Returns vote for voter. Returns None, if the voter cannot be found in `active_votes`.

            :param str voter: Voter for which the vote should be returned
            :param bool raw_data: If True, the raw data are returned
            :param pending_payout_HBD: When not None this value instead of the current
                value is used for calculating the rewards
            :type pending_payout_HBD: float, str
        """
        specific_vote = None
        if voter is None:
            voter = Account(self["author"], hive_instance=self.hive)
        else:
            voter = Account(voter, hive_instance=self.hive)
        if "active_votes" in self:
            for vote in self["active_votes"]:
                if voter["name"] == vote["voter"]:
                    specific_vote = vote
        else:
            active_votes = self.get_votes()
            for vote in active_votes:
                if voter["name"] == vote["voter"]:
                    specific_vote = vote 
        if specific_vote is not None and (raw_data or not self.is_pending()):
            return specific_vote
        elif specific_vote is not None:
            curation_reward = self.get_curation_rewards(pending_payout_HBD=True, pending_payout_value=pending_payout_value)
            specific_vote["curation_reward"] = curation_reward["active_votes"][voter["name"]]
            specific_vote["ROI"] = float(curation_reward["active_votes"][voter["name"]]) / float(voter.get_voting_value_HBD(voting_weight=specific_vote["percent"] / 100)) * 100
            return specific_vote
        else:
            return None

    def get_beneficiaries_pct(self):
        """ Returns the sum of all post beneficiaries in percentage
        """
        beneficiaries = self["beneficiaries"]
        weight = 0
        for b in beneficiaries:
            weight += b["weight"]
        return weight / 100.

    def get_rewards(self):
        """ Returns the total_payout, author_payout and the curator payout in HBD.
            When the payout is still pending, the estimated payout is given out.

            .. note:: Potential beneficiary rewards were already deducted from the
                      `author_payout` and the `total_payout`

            Example:::

                {
                    'total_payout': 9.956 HBD,
                    'author_payout': 7.166 HBD,
                    'curator_payout': 2.790 HBD
                }

        """
        if self.is_pending():
            total_payout = Amount(self["pending_payout_value"], hive_instance=self.hive)
            author_payout = self.get_author_rewards()["total_payout_HBD"]
            curator_payout = total_payout - author_payout
        else:
            author_payout = Amount(self["total_payout_value"], hive_instance=self.hive)
            curator_payout = Amount(self["curator_payout_value"], hive_instance=self.hive)
            total_payout = author_payout + curator_payout
        return {"total_payout": total_payout, "author_payout": author_payout, "curator_payout": curator_payout}

    def get_author_rewards(self):
        """ Returns the author rewards.

            Example::

                {
                    'pending_rewards': True,
                    'payout_HP': 0.912 HIVE,
                    'payout_HBD': 3.583 HBD,
                    'total_payout_HBD': 7.166 HBD
                }

        """
        if not self.is_pending():
            return {'pending_rewards': False,
                    "payout_HP": Amount(0, self.hive.hive_symbol, hive_instance=self.hive),
                    "payout_HBD": Amount(0, self.hive.hbd_symbol, hive_instance=self.hive),
                    "total_payout_HBD": Amount(self["total_payout_value"], hive_instance=self.hive)}

        median_hist = self.hive.get_current_median_history()
        if median_hist is not None:
            median_price = Price(median_hist, hive_instance=self.hive)
        beneficiaries_pct = self.get_beneficiaries_pct()
        curation_tokens = self.reward * 0.25
        author_tokens = self.reward - curation_tokens
        curation_rewards = self.get_curation_rewards()
        if self.hive.hardfork >= 20 and median_hist is not None:
            author_tokens += median_price * curation_rewards['unclaimed_rewards']

        benefactor_tokens = author_tokens * beneficiaries_pct / 100.
        author_tokens -= benefactor_tokens

        if median_hist is not None:
            hbd_hive = author_tokens * self["percent_hive_dollars"] / 20000.
            vesting_hive = median_price.as_base(self.hive.hive_symbol) * (author_tokens - hbd_hive)
            return {'pending_rewards': True, "payout_HP": vesting_hive, "payout_HBD": hbd_hive, "total_payout_HBD": author_tokens}
        else:
            return {'pending_rewards': True, "total_payout": author_tokens}

    def get_curation_rewards(self, pending_payout_HBD=False, pending_payout_value=None):
        """ Returns the curation rewards.

            :param bool pending_payout_HBD: If True, the rewards are returned in HBD and not in HIVE (default is False)
            :param pending_payout_value: When not None this value instead of the current
                value is used for calculating the rewards
            :type pending_payout_value: float, str

            `pending_rewards` is True when
            the post is younger than 7 days. `unclaimed_rewards` is the
            amount of curation_rewards that goes to the author (self-vote or votes within
            the first 30 minutes). `active_votes` contains all voter with their curation reward.

            Example::

                {
                    'pending_rewards': True, 'unclaimed_rewards': 0.245 HIVE,
                    'active_votes': {
                        'leprechaun': 0.006 HIVE, 'timcliff': 0.186 HIVE,
                        'st3llar': 0.000 HIVE, 'crokkon': 0.015 HIVE, 'feedyourminnows': 0.003 HIVE,
                        'isnochys': 0.003 HIVE, 'loshcat': 0.001 HIVE, 'greenorange': 0.000 HIVE,
                        'qustodian': 0.123 HIVE, 'jpphotography': 0.002 HIVE, 'thinkingmind': 0.001 HIVE,
                        'oups': 0.006 HIVE, 'mattockfs': 0.001 HIVE, 'thecrazygm': 0.003 HIVE, 'michaelizer': 0.004 HIVE,
                        'flugschwein': 0.010 HIVE, 'ulisessabeque': 0.000 HIVE, 'hakancelik': 0.002 HIVE, 'sbi2': 0.008 HIVE,
                        'zcool': 0.000 HIVE, 'hivehq': 0.002 HIVE, 'rowdiya': 0.000 HIVE, 'qurator-tier-1-2': 0.012 HIVE
                    }
                }

        """
        median_hist = self.hive.get_current_median_history()
        if median_hist is not None:
            median_price = Price(median_hist, hive_instance=self.hive)
        pending_rewards = False
        if "active_votes" in self:
            active_votes_list = self["active_votes"]
        else:
            active_votes_list = self.get_votes()
        if "total_vote_weight" in self:
            total_vote_weight = self["total_vote_weight"]
        else:
            total_vote_weight = 0
            for vote in active_votes_list:
                total_vote_weight += vote["weight"]
            
        if not self["allow_curation_rewards"] or not self.is_pending():
            max_rewards = Amount(0, self.hive.hive_symbol, hive_instance=self.hive)
            unclaimed_rewards = max_rewards.copy()
        else:
            if pending_payout_value is None and "pending_payout_value" in self:
                pending_payout_value = Amount(self["pending_payout_value"], hive_instance=self.hive)
            elif pending_payout_value is None:
                pending_payout_value = 0
            elif isinstance(pending_payout_value, (float, integer_types)):
                pending_payout_value = Amount(pending_payout_value, self.hive.hbd_symbol, hive_instance=self.hive)
            elif isinstance(pending_payout_value, str):
                pending_payout_value = Amount(pending_payout_value, hive_instance=self.hive)
            if pending_payout_HBD or median_hist is None:
                max_rewards = (pending_payout_value * 0.25)
            else:
                max_rewards = median_price.as_base(self.hive.hive_symbol) * (pending_payout_value * 0.25)
            unclaimed_rewards = max_rewards.copy()
            pending_rewards = True

        active_votes = {}

        for vote in active_votes_list:
            if total_vote_weight > 0:
                claim = max_rewards * int(vote["weight"]) / total_vote_weight
            else:
                claim = 0
            if claim > 0 and pending_rewards:
                unclaimed_rewards -= claim
            if claim > 0:
                active_votes[vote["voter"]] = claim
            else:
                active_votes[vote["voter"]] = 0

        return {'pending_rewards': pending_rewards, 'unclaimed_rewards': unclaimed_rewards, "active_votes": active_votes}

    def get_reblogged_by(self, identifier=None):
        """Shows in which blogs this post appears"""
        if not identifier:
            post_author = self["author"]
            post_permlink = self["permlink"]
        else:
            [post_author, post_permlink] = resolve_authorperm(identifier)
        if not self.hive.is_connected():
            return None
        self.hive.rpc.set_next_node_on_empty_reply(False)
        if self.hive.rpc.get_use_appbase():
            return self.hive.rpc.get_reblogged_by({'author': post_author, 'permlink': post_permlink}, api="follow")['accounts']
        else:
            return self.hive.rpc.get_reblogged_by(post_author, post_permlink, api="follow")

    def get_replies(self, raw_data=False, identifier=None):
        """ Returns content replies

            :param bool raw_data: When set to False, the replies will be returned as Comment class objects
        """
        if not identifier:
            post_author = self["author"]
            post_permlink = self["permlink"]
        else:
            [post_author, post_permlink] = resolve_authorperm(identifier)
        if not self.hive.is_connected():
            return None
        self.hive.rpc.set_next_node_on_empty_reply(False)
        if self.hive.rpc.get_use_appbase():
            content_replies = self.hive.rpc.get_content_replies({'author': post_author, 'permlink': post_permlink}, api="tags")
            if 'discussions' in content_replies:
                content_replies = content_replies['discussions']
        else:
            content_replies = self.hive.rpc.get_content_replies(post_author, post_permlink, api="tags")
        if raw_data:
            return content_replies
        return [Comment(c, hive_instance=self.hive) for c in content_replies]

    def get_all_replies(self, parent=None):
        """ Returns all content replies
        """
        if parent is None:
            parent = self
        if parent["children"] > 0:
            children = parent.get_replies()
            if children is None:
                return []
            for cc in children[:]:
                children.extend(self.get_all_replies(parent=cc))
            return children
        return []

    def get_parent(self, children=None):
        """ Returns the parent post with depth == 0"""
        if children is None:
            children = self
        while children["depth"] > 0:
            children = Comment(construct_authorperm(children["parent_author"], children["parent_permlink"]), hive_instance=self.hive)
        return children

    def get_votes(self, raw_data=False):
        """Returns all votes as ActiveVotes object"""
        if raw_data and "active_votes" in self:
            return self["active_votes"]
        from .vote import ActiveVotes
        return ActiveVotes(self, lazy=False, hive_instance=self.hive)

    def upvote(self, weight=+100, voter=None):
        """ Upvote the post

            :param float weight: (optional) Weight for posting (-100.0 -
                +100.0) defaults to +100.0
            :param str voter: (optional) Voting account

        """
        if weight < 0:
            raise ValueError("Weight must be >= 0.")
        last_payout = self.get('last_payout', None)
        if last_payout is not None:
            if formatToTimeStamp(last_payout) > 0:
                raise VotingInvalidOnArchivedPost
        return self.vote(weight, account=voter)

    def downvote(self, weight=100, voter=None):
        """ Downvote the post

            :param float weight: (optional) Weight for posting (-100.0 -
                +100.0) defaults to -100.0
            :param str voter: (optional) Voting account

        """
        if weight < 0:
            raise ValueError("Weight must be >= 0.")        
        last_payout = self.get('last_payout', None)
        if last_payout is not None:
            if formatToTimeStamp(last_payout) > 0:
                raise VotingInvalidOnArchivedPost
        return self.vote(-weight, account=voter)

    def vote(self, weight, account=None, identifier=None, **kwargs):
        """ Vote for a post

            :param float weight: Voting weight. Range: -100.0 - +100.0.
            :param str account: (optional) Account to use for voting. If
                ``account`` is not defined, the ``default_account`` will be used
                or a ValueError will be raised
            :param str identifier: Identifier for the post to vote. Takes the
                form ``@author/permlink``.

        """
        if not identifier:
            identifier = construct_authorperm(self["author"], self["permlink"])

        return self.hive.vote(weight, identifier, account=account)

    def edit(self, body, meta=None, replace=False):
        """ Edit an existing post

            :param str body: Body of the reply
            :param json meta: JSON meta object that can be attached to the
                post. (optional)
            :param bool replace: Instead of calculating a *diff*, replace
                the post entirely (defaults to ``False``)

        """
        if not meta:
            meta = {}
        original_post = self

        if replace:
            newbody = body
        else:
            newbody = make_patch(original_post["body"], body)
            if not newbody:
                log.info("No changes made! Skipping ...")
                return

        reply_identifier = construct_authorperm(
            original_post["parent_author"], original_post["parent_permlink"])

        new_meta = {}
        if meta is not None:
            if bool(original_post["json_metadata"]):
                new_meta = original_post["json_metadata"]
                for key in meta:
                    new_meta[key] = meta[key]
            else:
                new_meta = meta

        return self.hive.post(
            original_post["title"],
            newbody,
            reply_identifier=reply_identifier,
            author=original_post["author"],
            permlink=original_post["permlink"],
            json_metadata=new_meta,
        )

    def reply(self, body, title="", author="", meta=None):
        """ Reply to an existing post

            :param str body: Body of the reply
            :param str title: Title of the reply post
            :param str author: Author of reply (optional) if not provided
                ``default_user`` will be used, if present, else
                a ``ValueError`` will be raised.
            :param json meta: JSON meta object that can be attached to the
                post. (optional)

        """
        return self.hive.post(
            title,
            body,
            json_metadata=meta,
            author=author,
            reply_identifier=self.identifier)

    def delete(self, account=None, identifier=None):
        """ Delete an existing post/comment

            :param str account: (optional) Account to use for deletion. If
                ``account`` is not defined, the ``default_account`` will be
                taken or a ValueError will be raised.

            :param str identifier: (optional) Identifier for the post to delete.
                Takes the form ``@author/permlink``. By default the current post
                will be used.

            .. note:: A post/comment can only be deleted as long as it has no
                      replies and no positive rshares on it.

        """
        if not account:
            if "default_account" in self.hive.config:
                account = self.hive.config["default_account"]
        if not account:
            raise ValueError("You need to provide an account")
        account = Account(account, hive_instance=self.hive)
        if not identifier:
            post_author = self["author"]
            post_permlink = self["permlink"]
        else:
            [post_author, post_permlink] = resolve_authorperm(identifier)
        op = operations.Delete_comment(
            **{"author": post_author,
               "permlink": post_permlink})
        return self.hive.finalizeOp(op, account, "posting")

    def rehive(self, identifier=None, account=None):
        """ Rehive a post

            :param str identifier: post identifier (@<account>/<permlink>)
            :param str account: (optional) the account to allow access
                to (defaults to ``default_account``)

        """
        if not account:
            account = self.hive.configStorage.get("default_account")
        if not account:
            raise ValueError("You need to provide an account")
        account = Account(account, hive_instance=self.hive)
        if identifier is None:
            identifier = self.identifier
        author, permlink = resolve_authorperm(identifier)
        json_body = [
            "reblog", {
                "account": account["name"],
                "author": author,
                "permlink": permlink
            }
        ]
        return self.hive.custom_json(
            id="follow", json_data=json_body, required_posting_auths=[account["name"]])


class RecentReplies(list):
    """ Obtain a list of recent replies

        :param str author: author
        :param bool skip_own: (optional) Skip replies of the author to him/herself.
            Default: True
        :param Hive hive_instance: Hive() instance to use when accesing a RPC
    """
    def __init__(self, author, skip_own=True, lazy=False, full=True, hive_instance=None):
        self.hive = hive_instance or shared_hive_instance()
        if not self.hive.is_connected():
            return None
        self.hive.rpc.set_next_node_on_empty_reply(True)
        state = self.hive.rpc.get_state("/@%s/recent-replies" % author)
        replies = state["accounts"][author].get("recent_replies", [])
        comments = []
        for reply in replies:
            post = state["content"][reply]
            if skip_own and post["author"] == author:
                continue
            comments.append(Comment(post, lazy=lazy, full=full, hive_instance=self.hive))
        super(RecentReplies, self).__init__(comments)


class RecentByPath(list):
    """ Obtain a list of votes for an account

        :param str account: Account name
        :param Hive hive_instance: Hive() instance to use when accesing a RPC
    """
    def __init__(self, path="promoted", category=None, lazy=False, full=True, hive_instance=None):
        self.hive = hive_instance or shared_hive_instance()
        if not self.hive.is_connected():
            return None
        self.hive.rpc.set_next_node_on_empty_reply(True)
        state = self.hive.rpc.get_state("/" + path)
        replies = state["discussion_idx"][''].get(path, [])
        comments = []
        for reply in replies:
            post = state["content"][reply]
            if category is None or (category is not None and post["category"] == category):
                comments.append(Comment(post, lazy=lazy, full=full, hive_instance=self.hive))
        super(RecentByPath, self).__init__(comments)