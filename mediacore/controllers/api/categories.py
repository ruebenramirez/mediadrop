# This file is a part of MediaCore CE (http://www.mediacorecommunity.org),
# Copyright 2009-2012 MediaCore Inc., Felix Schwarz and other contributors.
# For the exact contribution history, see the git revision log.
# The source code contained in this file is licensed under the GPLv3 or
# (at your option) any later version.
# See LICENSE.txt in the main project directory, for more information.

import logging
from datetime import datetime, timedelta

from paste.util.converters import asbool
from pylons import app_globals, request
from sqlalchemy import orm

from mediacore.controllers.api import APIException, get_order_by
from mediacore.lib import helpers
from mediacore.lib.base import BaseController
from mediacore.lib.compat import any
from mediacore.lib.decorators import expose
from mediacore.lib.helpers import get_featured_category, url_for
from mediacore.lib.thumbnails import thumb
from mediacore.model import Category
from mediacore.model.meta import DBSession

log = logging.getLogger(__name__)

order_columns = {
    'id': Category.id,
    'name': Category.name,
    'slug': Category.slug,
    'media_count': 'media_count %s',
}

class CategoriesController(BaseController):
    """
    JSON Category API
    """

    @expose('json')
    def index(self, order=None, offset=0, limit=10, api_key=None, **kwargs):
        """Query for a flat list of categories.

        :param id: An :attr:`id <mediacore.model.media.Category.id>` for lookup
        :type id: int

        :param name: A :attr:`name <mediacore.model.media.Category.name>`
            for lookup
        :type name: str

        :param slug: A :attr:`slug <mediacore.model.media.Category.slug>`
            for lookup
        :type slug: str

        :param order:
            A column name and 'asc' or 'desc', seperated by a space.
            The column name can be any one of the returned columns.
            Defaults to newest category first (id desc).
        :type order: str

        :param offset:
            Where in the complete resultset to start returning results.
            Defaults to 0, the very beginning. This is useful if you've
            already fetched the first 50 results and want to fetch the
            next 50 and so on.
        :type offset: int

        :param limit:
            Number of results to return in each query. Defaults to 10.
            The maximum allowed value defaults to 50 and is set via
            :attr:`request.settings['api_media_max_results']`.
        :type limit: int

        :param api_key:
            The api access key if required in settings
        :type api_key: unicode or None

        :rtype: JSON-ready dict
        :returns: The returned dict has the following fields:

            count (int)
                The total number of results that match this query.
            categories (list of dicts)
                A list of **category_info** dicts, as generated by the
                :meth:`_info <mediacore.controllers.api.categories.CategoriesController._info>`
                method. The number of dicts in this list will be the lesser
                of the number of matched items and the requested limit.

        """
        if asbool(request.settings['api_secret_key_required']) \
            and api_key != request.settings['api_secret_key']:
            return dict(error='Authentication Error')

        if any(key in kwargs for key in ('id', 'slug', 'name')):
            kwargs['offset'] = offset
            kwargs['limit'] = limit
            kwargs['tree'] = False
            return self._get_query(**kwargs)

        return self._index_query(order, offset, limit, tree=False)

    @expose('json')
    def tree(self, depth=10, api_key=None, **kwargs):
        """Query for an expanded tree of categories.

        :param id: A :attr:`mediacore.model.media.Category.id` to lookup the parent node
        :type id: int
        :param name: A :attr:`mediacore.model.media.Category.name` to lookup the parent node
        :type name: str
        :param slug: A :attr:`mediacore.model.media.Category.slug` to lookup the parent node
        :type slug: str

        :param depth:
            Number of level deep in children to expand. Defaults to 10.
            The maximum allowed value defaults to 10 and is set via
            :attr:`request.settings['api_tree_max_depth']`.
        :type limit: int
        :param api_key:
            The api access key if required in settings
        :type api_key: unicode or None
        :rtype: JSON-ready dict
        :returns: The returned dict has the following fields:

            count (int)
                The total number of results that match this query.
            categories (list of dicts)
                A list of **category_info** dicts, as generated by the
                :meth:`_info <mediacore.controllers.api.categories.CategoriesController._info>`
                method. Each of these dicts represents a category at the top
                level of the hierarchy. Each dict has also been modified to
                have an extra 'children' field, which is a list of
                **category_info** dicts representing that category's children
                within the hierarchy.

        """
        if asbool(request.settings['api_secret_key_required']) \
            and api_key != request.settings['api_secret_key']:
            return dict(error='Authentication Error')
        if any(key in kwargs for key in ('id', 'slug', 'name')):
            kwargs['depth'] = depth
            kwargs['tree'] = True
            return self._get_query(**kwargs)

        return self._index_query(depth=depth, tree=True)

    def _index_query(self, order=None, offset=0, limit=10, tree=False, depth=10, **kwargs):
        """Query a list of categories"""
        if asbool(tree):
            query = Category.query.roots()
        else:
            query = Category.query

        if not order:
            order = 'id asc'

        query = query.order_by(get_order_by(order, order_columns))

        start = int(offset)
        limit = min(int(limit), int(request.settings['api_media_max_results']))
        depth = min(int(depth), int(request.settings['api_tree_max_depth']))

        # get the total of all the matches
        count = query.count()

        query = query.offset(start).limit(limit)
        categories = self._expand(query.all(), asbool(tree), depth)

        return dict(
           categories = categories,
           count = count,
        )

    def _get_query(self, id=None, name=None, slug=None, tree=False, depth=10, **kwargs):
        """Query for a specific category item by ID, name or slug and optionally expand the children of this category."""
        query = Category.query
        depth = min(int(depth), int(request.settings['api_tree_max_depth']))

        if id:
            query = query.filter_by(id=id)
        elif name:
            query = query.filter_by(name=name)
        else:
            query = query.filter_by(slug=slug)

        try:
            category = query.one()
        except (orm.exc.NoResultFound, orm.exc.MultipleResultsFound):
            return dict(error='No Match found')

        return dict(
            category = self._expand(category, tree, depth=depth),
        )

    def _expand(self, obj, children=False, depth=0):
        """Expand a category object into json."""
        if isinstance(obj, list):
            data = [self._expand(x, children, depth) for x in obj]
        elif isinstance(obj, Category):
            data = self._info(obj)
            if children and depth > 0:
                data['children'] = self._expand(obj.children, children, depth - 1)
        return data

    def _info(self, cat):
        """Return a JSON-ready dict representing the given category instance.

        :rtype: JSON-Ready dict
        :returns: The returned dict has the following fields:

            id (int)
                The numeric unique identifier,
                :attr:`Category.id <mediacore.model.categories.Category.id>`
            slug (unicode)
                The more human readable unique identifier,
                :attr:`Category.slug <mediacore.model.categories.Category.slug>`
            name (unicode)
                The human readable
                :attr:`name <mediacore.model.categories.Category.name>`
                of the category.
            parent (unicode or None)
                the :attr:`slug <mediacore.model.categories.Category.slug>`
                of the category's parent in the hierarchy, or None.
            media_count (int)
                The number of media items that are published in this category,
                or in its sub-categories.

        """
        return dict(
            id = cat.id,
            name = cat.name,
            slug = cat.slug,
            parent = cat.parent_id,
            media_count = cat.media_count_published,
        )
