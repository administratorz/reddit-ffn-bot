"""
This module stores the comment saving functionality.
"""
import contextlib
import logging

import praw.objects


class CommentList(object):
    """
    Stores the comment list.

    It will not load the comment list until needed.
    """

    def __init__(self, filename, dry=False):
        self.clist = None
        self.filename = filename
        self.dry = dry
        self.logger = logging.getLogger("CommmentList")
        self._transaction_stack = []

    def __enter__(self):
        self._init_clist()
        self._transaction_stack.append(self.clist.copy())
        return self

    def __exit__(self, exc, val, tb):
        last_transaction = self._transaction_stack.pop()
        if exc:
            self.clist = last_transaction
        self.save()

    def _load(self):
        self.clist = set()
        self.logger.info("Loading comment list...")
        with contextlib.suppress(FileNotFoundError):
            with open(self.filename, "r") as f:
                for line in f:
                    data = line.strip()

                    # Convert from old format into the new format.
                    if data.startswith("SUBMISSION"):
                        self.logger.debug("Converting %s into new format"%data)
                        data = data.replace("SUBMISSION_", "t3_", 1)
                    elif not data.startswith("t") and data[2] != "_":
                        self.logger.debug("Converting %s into new format"%data)
                        data = "t1_" + data

                    self.clist.add(data)

    def _save(self):
        if not len(self._transaction_stack):
            self.save()

    def save(self):
        if self.dry or self.clist is None:
            return

        self.logger.info("Saving comment list...")
        with open(self.filename, "w") as f:
            for item in self.clist:
                f.write(item + "\n")

    def __contains__(self, cid):
        self._init_clist()
        cid = self._convert_object(cid)
        self.logger.debug("Querying: " + cid)
        return cid in self.clist

    def add(self, cid):
        self._init_clist()
        cid = self._convert_object(cid)
        self.logger.debug("Adding comment to list: " + cid)
        if cid in self:
            self.clist.add(cid)
            self._save()

    def __del__(self):
        """
        Do not rely on this function.
        The GC is known for not calling the deconstructor
        in certain cases.
        """
        self.save()

    def _init_clist(self):
        if self.clist is None:
            self._load()

    @staticmethod
    def _convert_object(cid):
        if isinstance(cid, praw.objects.RedditContentObject):
            cid = cid.fullname
        return cid

    def __len__(self):
        self._init_clist()
        return len(self.clist)

    def __iter__(self):
        self._init_clist()
        return iter(self.clist)
