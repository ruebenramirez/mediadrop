# This file is a part of MediaCore CE (http://www.mediacorecommunity.org),
# Copyright 2009-2012 MediaCore Inc., Felix Schwarz and other contributors.
# For the exact contribution history, see the git revision log.
# The source code contained in this file is licensed under the GPLv3 or
# (at your option) any later version.
# See LICENSE.txt in the main project directory, for more information.

from mediacore.tests import *

class TestTagsController(TestController):

    def test_index(self):
        response = self.app.get(url(controller='admin/tags', action='index'))
        # Test response...
