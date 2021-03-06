__author__ = 'yuejin'

import csv, pickle, math, os, pandas
from copy import copy, deepcopy
from collections import Iterable
import numpy as np
import random
from time import time
from pprint import pprint
from multiprocessing import cpu_count
from numpy.core.fromnumeric import mean, var
from numpy.lib.scimath import sqrt
from itertools import product
from scipy.stats import mode
from collections import OrderedDict
import matplotlib.pyplot as plt

from sklearn.base import is_classifier, clone
from sklearn.metrics import *
from sklearn.pipeline import Pipeline
from sklearn.base import BaseEstimator, TransformerMixin
from sklearn.cross_validation import StratifiedShuffleSplit, check_cv, LeavePOut
from sklearn.preprocessing import StandardScaler, MinMaxScaler, Imputer
from sklearn.grid_search import GridSearchCV
from sklearn.ensemble import ExtraTreesRegressor

from pool_JJ import MyPool


def getCol(m, colIndices):
    """ Get specified columns of a matrix (in the form of list of lists)
    @param m: list of lists
    @param colIndices: indices to get
    @return: a new list of lists (or elements, if len(colIndices)==1)
    """

    # a single value
    if not isinstance(colIndices, (list, tuple)):
        return [r[colIndices] for r in m]

    # a single column
    if len(colIndices)==1:
        return [r[colIndices[0]] for r in m]

    # multiple columns
    return [[r[i] for i in colIndices] for r in m]


def integerizeList(l):
    """ Convert a list of any object to a list of ints
    @param l: the list to be converted
    @return: the new list and a map of factors
    """

    uniqVals = np.unique(l)
    newVals = range(len(uniqVals))
    factorMap = dict(zip(uniqVals, newVals))

    newList = [factorMap[v] for v in l]
    return newList, factorMap


def csv2dict(fname, hasHeader, fieldnames=None, dataTypes=None, colIndices=None, defaultNumValue=-1):
    """ load a csv file as a dict of the format {col1 name: col1 values, col2 name: col2 values, ..., coln name: coln values}
        @param hasHeader if True, uses the first row as header; otherwise uses "col1",...,"col n"
        @param colIndices which columns to pick out. Default to all columns. Note that fieldnames are the fieldnames of all columns regardless of colIndices
        @param defaultValues the values to use when the data is missing or of unexpected type
    """

    reader = csv.reader(open(fname, 'rb'), delimiter=',')

    # read header
    if hasHeader:
        fieldnames = reader.next()

    print fieldnames

    data = [tuple(row) for row in reader]
    totalNumCols = len(data[0])
    if not colIndices:
        colIndices = range(totalNumCols)
    data = [tuple(row[i] for i in colIndices) for row in data]

    if dataTypes is not None:

        # figure out fieldnames and dtype
        if not fieldnames: fieldnames = ['']*len(colIndices)
        if fieldnames and len(fieldnames)>len(colIndices): fieldnames = [fieldnames[i] for i in colIndices]
        dtype = zip(fieldnames, dataTypes)

        # convert data type
        numCols = len(data[0])
        res = []
        for row in data:
            temp = []
            for i in range(numCols):
                if (dataTypes[i] in [np.int, np.float]):
                    try:
                        temp.append(dataTypes[i](row[i]))
                    except:
                        temp.append(defaultNumValue)
                else:
                    temp.append(row[i])

            res.append(tuple(temp))

        res = np.array(res, dtype=dtype)

    else:
        res = np.array(data)

    return res

def rescaleData(data):
    """ rescales data (x-min)/(max-min)
    @param data: data to be scaled
    @return: (rescaled data with the same shape as the original data, meanVec, dVec, the transformer itself)
    """

    minVec = data.min(axis=0)
    maxVec = data.max(axis=0)
    d = 1.0 * (maxVec-minVec)

    # fix constant-valued ranges
    for i, v in enumerate(d):
        if v==0:
            if maxVec[i]==0:
                d[i] = 1
            else:
                d[i] = maxVec[i]

    res = (data - minVec)/d

    def foo(givenData):
        assert givenData.shape[1]==data.shape[1], "Only arrays of %d columns are handled." % data.shape[1]
        return (givenData - minVec)/d

    return res, minVec, d, foo

def normalizeData(data, meanOnly = False):
    """
    normalize data by subtracting mean and dividing by sd per COLUMN
    @param data: an array
    @param meanOnly: if True subtract mean only; otherwise divide by sd too
    @return: (an array with the same dimension as data, mean, stds, the transformer)
    """

    # compute the new data
    m = mean(data, axis=0)
    res = data - m

    if meanOnly:
        stds = 1
    else:
        stds = sqrt(var(data, axis=0))
        stds[stds==0] = 1   # to avoid dividing by 0

        res /= stds

    # figure out the transformer
    def foo(givenData):
        assert givenData.shape[1]==data.shape[1], "Only arrays of %d columns are handled." % data.shape[1]
        return (givenData - m)/stds

    return res, m, stds, foo

def makePipe(items):
    """
    make a pipe and a parameter object using the list of steps
    @param items: a list of items of the form (name: (object, params))
    @return: pipeline, parameters dict
    """

    steps = []      # steps of the pipeline
    paramDict = {}  # parameters of the pipeline

    for name, (clf, params) in items:
        steps.append((name, clf))

        for k, v in params.iteritems():
            paramDict[name + '__' + k] = v

    return Pipeline(steps), OrderedDict(paramDict)

def printItalics(s):
    """ prints the string s in italics
    """

    print "\x1B[3m%s\x1B[23m" % s

def printDoneTime(t0, s=''):
    """ prints "done in ... seconds"
    @param t0: starting time
    @param s: stuff to print
    """
    if s=='':
        printItalics('Done in %0.3fs.' % (time() - t0))
    else:
        printItalics('%s took %0.3fs.' % (s, time() - t0))

def saveObject(obj, fname):
    """
    Save an object to file
    @param obj: the object to be saved
    @param fname: the featureSelectionOutput filename
    @return: nothing
    """
    with open(fname, 'wb') as output:
        pickle.dump(obj, output, protocol=2)

def loadObject(fname):
    """
    load an object from file
    @param fname: file name
    @return: the object saved in the file
    """

    input = open(fname, 'rb')
    res = pickle.load(input)
    input.close()

    return res

def benchmark(clf, X_train, y_train, X_test, y_test):
    """ train, predict and run metrics on a classifier
    """
    print 80*'_'
    print 'Training: '
    print clf
    t0 = time()
    clf.fit(X_train, y_train)
    train_time = time() - t0
    print 'train time: %0.3fs' % train_time

    t0 = time()
    pred = clf.predict(X_test)
    test_time = time() - t0
    print 'test time: %0.3fs' % test_time

    score = f1_score(y_test, pred)
    print 'f1-score:   %0.3f' % score

    if hasattr(clf, 'coef_'):
        print 'dimensionality: %d' % clf.coef_.shape[1]
#        print 'density: %f' % density(clf.coef_)
        print


    print '--- classification report:'
    print classification_report(y_test, pred)


    print '--- confusion matrix:'
    print confusion_matrix(y_test, pred)

    print
    clf_descr = str(clf).split('(')[0]

    return clf_descr, score, train_time, test_time

def fillInMissingValues(origdata, method):
    """ fill in nan values in a data numpy array
    @param origdata: a numpy array (unchanged in the end)
    @param method: 'mean': fill in with mean of the column
                   'median': fill in with median of the column
                   a single value: fill in with all missing values with this value
                   a list/array of data.shape[1] values: one constant filler for each column
    @return: a numpy array with the same dimensions as the input data
    """


    data = copy(origdata)
    numCols = data.shape[1]

    unfixed = False # if there are still NANs are "column-sweep"

    for col in range(numCols):
        missingInd = np.array([math.isnan(v) for v in data[:,col]])
        availInd = np.invert(missingInd)
        if availInd.sum() == 0: unfixed = True

        if method=='mean':
            data[missingInd, col] = np.mean(data[availInd, col])

        elif method=='median':
            data[missingInd, col] = np.median(data[availInd, col])

        elif not isinstance(method, str):
            if isinstance(method, Iterable):
                assert len(method) == numCols, 'Expected to have %d elements.' % numCols
                data[missingInd, col] = method[col]
            else:
                data[missingInd, col] = method

    if unfixed:
        for row in range(data.shape[0]):
            missingInd = np.array([math.isnan(v) for v in data[row, :]])
            availInd = np.invert(missingInd)

            if method=='mean':
                data[row, missingInd] = np.mean(data[row, availInd])

            elif method=='median':
                data[row, missingInd] = np.median(data[row, availInd])

            # it's not possible to reach here if method were constant(s)

    return data


## standardizes the data in an array
class Normalizer(BaseEstimator, TransformerMixin):
    def __init__(self, method='standardize'):
        """ Constructor
        @param method: method of normalization. The ones currently supported are:
                'standardize': (x-mean)/sd
                'rescale': (x-min)/(max-min)
        @return: nothing.
        """
        assert method in ['standardize', 'rescale'], 'Unexpected method %s'%method

        self.method = method

        if method == 'standardize':
            self._scaler = StandardScaler()
        else:
            self._scaler = MinMaxScaler()

    def fit(self, X, y=None, **params):
        """
        @return: the caller itself
        """

        self._scaler.fit(X, y)

        return self

    def transform(self, X, **params):
        """
        @return: transformed data
        """

        return self._scaler.transform(X)

    def fit_transform(self, X, y=None, **params):
        """
        @return: transformed data
        """

        return self._scaler.fit_transform(X, y, **params)


# fills in missing values in an array
class MissingValueFiller(BaseEstimator, TransformerMixin):
    def __init__(self, method='mean'):
        """ Constructor
        @param method: method of filling in missing values. The ones currently supported are:
                'mean': fills in with the mean of the available data
                'median': fills in with the median of the available data
                a single value: fill in with all missing values with this value
                a list/array of data.shape[1] values: one constant filler for each column
        @return: nothing.
        """
        self.method = method

    def fit(self, X, y=None, **params):
        return self

    def transform(self, X, **params):
        return fillInMissingValues(X, self.method)

    def fit_transform(self, X, y=None, **params):
        return self.transform(X)

def savePipeToFile(pipe, outputFname, **args):
    """
    save (via pickling) a pipe to file
    the items saved are best_estimator_, grid_scores_, param_grid, best_params_ and anything else passed via args
    @param pipe:
    @param outputFname:
    @param args: anything else to be saved, e.g. score=...
    @return:
    """
    contentToSave = {'best_estimator_': pipe.best_estimator_, 'grid_scores_': pipe.grid_scores_,
                     'param_grid': pipe.param_grid, 'best_params_': pipe.best_params_}

    for k,v in args.iteritems():
        contentToSave[k] = v

    saveObject(contentToSave, outputFname)

def mask2DArrayByCol(arr, colValDict):
    """ shows only rows where all columns are desired
    @param colValDict: a dictionary of {col to mask, val to show}
    @return: (masked array, the mask)
    """

    mask = np.array([arr[:, col]==val for col,val in colValDict.iteritems()]).all(axis=0)
    res = arr[mask]

    return res, mask

def groupArrayByCols(arr, colIndices, removeColumnsAfterwards):
    """
    @return: {vals for given columns: (resulting array with valid rows, mask), ...}
    """
    res = {}
    uniqVals = [np.unique(arr[:,colInd]) for colInd in colIndices]    # [(col, uniq vals for that col), ...]

    for vals in product(*uniqVals):
        curRes, mask = mask2DArrayByCol(arr, dict(zip(colIndices, vals)))
        if removeColumnsAfterwards:
            curRes = np.delete(curRes, colIndices, axis=1)

        res[vals] = (curRes, mask)

    # it's kinda funny to put this check here...
    assert (np.sum([v[1] for v in res.values()], axis=0) == np.repeat(1, arr.shape[0])).all(), "Masks must split the original array."
    return res

def contains(big, small):
    """
    @type big Iterable
    @type small Iterable
    """

    return set(small).issubset(set(big))


def reverseDict(d):
    """ reverse a dictionary
    @type d: dict
    @param d: the dictionary to be reversed
    @rtype dict
    """

    return dict((v,k) for k,v in d.iteritems())


class DatasetPair:
    """
    represents a dataset of X and Y values
    """
    def __init__(self, X, Y=None, fieldNames=None):
        if fieldNames is None:
            self.fieldNames = ["X"+str(c) for c in range(X.shape[1])]
        else:
            self.fieldNames = copy(fieldNames)

        if Y is not None:
            assert X.shape[0]==Y.shape[0], 'X (%d rows) and Y (%d rows) have different number of rows.'%(X.shape[0], Y.shape[0])
        assert X.shape[1]==len(self.fieldNames), 'X (%d columns) does not agree with field names (length %d).' %(X.shape[1], len(fieldNames))

        self.X = copy(X)
        self.Y = copy(Y)
        self.dataCount = X.shape[0]

    def spliceByColumnIndices(self, colIndices, removeColumns):
        """ group by given column indices
        @param colIndices: indices of the columns to remove
        @param removeColumns: whether to remove the given columns afterwards
        @return: a dictionary of {vals : Datasetpair object}
        """

        assert contains(range(len(self.fieldNames)), colIndices), "Some column indices are out of range."

        res = {}

        if removeColumns:
            newFieldNames = [self.fieldNames[i] for i in xrange(len(self.fieldNames)) if i not in colIndices]
        else:
            newFieldNames = self.fieldNames

        for k, (x, mask) in groupArrayByCols(self.X, colIndices, removeColumns).iteritems():
            res[k] = DatasetPair(X=x, Y=None if self.Y is None else self.Y[mask], fieldNames=newFieldNames)

        return res

    def spliceByColumnNames(self, colNames, removeColumns):
        """ group by given column names
        @param colNames: names of the columns to remove
        @param removeColumns: whether to remove the given columns afterwards
        @return: a dictionary of {vals : Datasetpair object}
        """
        assert contains(self.fieldNames, colNames), "Some field names are invalid. Given: "

        return self.spliceByColumnIndices([self.fieldNames.index(name) for name in colNames], removeColumns)


    def getPair(self):
        """
        @return: (X, Y)
        """
        return self.X, self.Y


    def split(self, size, randomState=0):
        """
        does NOT change self
        @param size: either an integer indicating the number of elements in the test set, or a float representing a proportion
        @return: (train, test)
        """
        x_train = y_train = x_test = y_test = sampleWeights_train = None

        for train_index, test_index in StratifiedShuffleSplit(self.Y, 1, test_size=size, random_state=randomState):
            x_train = self.X[train_index]
            y_train = self.Y[train_index]
            x_test = self.X[test_index]
            y_test = self.Y[test_index]

        return DatasetPair(x_train, y_train, self.fieldNames), DatasetPair(x_test, y_test, self.fieldNames)


    @staticmethod
    def combine(objList):
        """
        combines multiple DatasetPair objects into one by appending them
        @param objList: a list of DatasetPair objects
        @rtype DatasetPair
        """

        return DatasetPair(np.vstack(obj.X for obj in objList), np.vstack(obj.Y for obj in objList), objList[0].fieldNames)


class MajorityPredictor(BaseEstimator, TransformerMixin):
    """ simply predicts the outcome to be the majority of the previous outcomes
    """
    def __init__(self):
        self._output = None

    def fit(self, y):
        self._output = mode(y)[0][0]
        return self

    def predict(self, X):
        return np.repeat(self._output, X.shape[0])


def splitTrainTest(X, y, testSize):
    """
    shuffle-splits data
    @type X np.array
    @type y np.array
    @return: trainX, trainY, testX, testY
    """

    nRows = X.shape[0]
    allInd = range(nRows)
    random.shuffle(allInd)

    nTrain = int((1-testSize)*nRows)
    trainInd = allInd[:nTrain]
    testInd = allInd[nTrain:]

    return X[trainInd], y[trainInd], X[testInd], y[testInd]


def cvScores(clf, X, y, scoreFuncsToUse='all', numCVs=10, n_jobs=1, test_size=0.25, y_test=None, verbose=True):
    """
    evaluates cv scores under numerous measures
    @param clf: the classifier
    @param X:
    @param y:
    @param numCVs: number of StratifiedShuffleSplit iterations
    @param n_jobs:
    @param scoreFunc: which score function to use. if 'all' then uses all
    @return:
    """
    res = {}
    if verbose:
        print '------- CV Scores -------'

    scoreFuncs = {'accuracy_score':accuracy_score, 'auc_score': roc_auc_score, 'average_precision_score':average_precision_score,
                  'f1_score': f1_score, 'hinge_loss':hinge_loss, 'precision_score':precision_score, 'recall_score':recall_score}

    for name, scoreFunc in scoreFuncs.iteritems():

        if not (scoreFuncsToUse=='all' or name==scoreFuncsToUse or name in scoreFuncsToUse): continue
        if verbose:
            print '---', name, '---'

        try:
            scores = jjcross_val_score(clf, X, y, score_func=scoreFunc,
                                       cv = StratifiedShuffleSplit(y if y_test is None else y_test,
                                                                   n_iter=numCVs,
                                                                   test_size=test_size),
                                       n_jobs=n_jobs, y_test=y_test)

            if verbose: print 'Results: %0.4f +/- %0.4f' % (scores.mean(), 2*scores.std())
            res[name] = (scores.mean(), scores.std())
        except Exception, e:
            if verbose: print 'Error caught. :(', e.message

    return res


def jjcross_val_score_inner(args):
    """
    @param args: parameters are read in as a list
     [trainInds, testInds]
    @return: score
    """

    global X, y, clf, score_func, fit_params, weights, y_test, use_predProb_instead
    trainInds, testInds = args

    newClf = clone(clf)

    if weights is not None and 'sample_weight' in newClf.fit.func_code.co_varnames:
        newClf.fit(X[trainInds], y[trainInds], sample_weight=weights[trainInds], **fit_params)
    else:
        newClf.fit(X[trainInds], y[trainInds], **fit_params)

    pred = newClf.predict_proba(X[testInds])[:, 0] if use_predProb_instead else newClf.predict(X[testInds])


    score = score_func((y if y_test is None else y_test)[testInds], pred) if weights is None \
        else score_func((y if y_test is None else y_test)[testInds], pred, sample_weight=weights[testInds])

    return score


def jjcross_val_score_init(*args):
    global X, y, clf, score_func, fit_params, weights, y_test, use_predProb_instead
    X, y, clf, score_func, fit_params, weights, y_test, use_predProb_instead = args


def getNumCvFolds(cv):
    """
    @param cv: gets the number of folds in a cv object
    @return:
    """

    if isinstance(cv, int):
        return cv
    elif isinstance(cv, list):
        return len(cv)
    elif hasattr(cv, 'n_iter'):
        return cv.n_iter
    else:
        return cv.n_folds


def jjcross_val_score(clf, X, y, score_func, cv, y_test=None, n_jobs=cpu_count(), use_predProb_instead=False,
                      fit_params=None, weights=None, verbose=True):
    """

    @param clf:
    @param X: np.array
    @param y: np.array
    @param y_test: np.array. If not None then the Y's used for testing are different from the ones used for training.
    @param score_func: a score function of the form func(y_true, y_pred)
    @param cv: either an integer indicating the number of StratifiedKFold folds, or an iterable
    @param n_jobs:
    @param fit_params: parameters to pass to the estimator's fit method
    @param socre_params: parameters to pass to score_func
    @return: array of scores
    """

    cv = check_cv(cv, X, y, classifier=is_classifier(clf))

    # print 'cv:', cv
    fit_params = fit_params if fit_params is not None else {}
    # weights = weights if weights is not None else {}

    if n_jobs > 1:
        # figure out the number of folds
        n_jobs = min(n_jobs, getNumCvFolds(cv))
        # print 'jjcvscore with %d proceses' % n_jobs
        pool = MyPool(n_jobs, initializer=jjcross_val_score_init,
                      initargs=(X, y, clf, score_func, fit_params, weights, y_test, use_predProb_instead))
        data = [[trainInds, testInds] for trainInds, testInds in cv]
        temp = pool.map_async(jjcross_val_score_inner, data)
        temp.wait()
        scores = temp.get()
        pool.close()
        pool.join()
    else:
        # print 'jjcvscore single thread'
        scores = []
        fold = 1
        for trainInds, testInds in cv:
            # print '=========== fold %d ===========' % fold

            trainX = X[trainInds]
            trainY = y[trainInds]
            testX = X[testInds]
            testY = (y if y_test is None else y_test)[testInds]

            if weights is not None:
                trainWeights = weights[trainInds]
                testWeights = weights[testInds]

            if len(np.unique(trainY))==1:
                yPred = np.repeat(trainY[0], len(testY))
            else:
                clonedClf = clone(clf)

                if weights is not None and 'sample_weight' in clonedClf.fit.func_code.co_varnames:
                    try:
                        clonedClf.fit(trainX, trainY, sample_weight=trainWeights, **fit_params)
                    except:
                        clonedClf.fit(trainX, trainY, **fit_params)
                else:
                    clonedClf.fit(trainX, trainY, **fit_params)

                yPred =  clonedClf.predict_proba(testX)[:, 0] if use_predProb_instead else clonedClf.predict(testX)

            if weights is None:
                score = score_func(testY, yPred)
            else:
                score = score_func(testY, yPred, sample_weight=testWeights)

            scores.append(score)
            fold += 1


    if verbose:
        for i, score in enumerate(scores):
            print 'Fold %d, score = %f' % (i, score)

        print ">>>>>>>> %d-fold Score (mean, cv) = (%f, %f)" % (len(cv), np.mean(scores), np.std(scores)/np.mean(scores))

    return np.array(scores)


def diffLists(a, b):
    """
    @return: a-b (as a list)
    """

    return list(set(a) - set(b))


def runPool(aPool, innerFunc, inputData):
    """ runs a pool and returns the result
    """

    temp = aPool.map_async(innerFunc, inputData)
    temp.wait()

    return np.array(temp.get())


def plot_histogram(vec, numBins, title='', xLabel='', yLabel='Count', faceColor = 'green', alpha=1, line=None, lineColor='r'):
    """ plots and shows a histogram
    @param line: y values which are used to plot a line, must have numBins elements
    """

    # the histogram of the data
    n, bins, patches = plt.hist(vec, numBins, facecolor=faceColor, alpha=alpha)

    # add a 'best fit' line
    if line is not None:
        plt.plot(bins, line, lineColor + '--')

    plt.xlabel(xLabel)
    plt.ylabel(yLabel)
    plt.title(title)

    plt.show()


def print_GSCV_info(gsv, isGAJJ=False, bestParams=None):
    """
    @param isGAJJ: true iff gscv is a GAGridSearchCV_JJ object; otherwise it is a GridSearchCV object
    @param bestParams: used only if isGAJJ is true
    """

    if isGAJJ:
        print '\n>>> Best Evaluable:'
        print gsv.bestEvaluable
        print '\n>>> Best score:', gsv.bestEvaluation
        print '\n>>> Best Params:'
        pprint(bestParams)
    else:
        print '\n>>> Grid scores:'
        pprint(gsv.grid_scores_)
        print '\n>>> Best Estimator:'
        pprint(gsv.best_estimator_)
        print '\n>>> Best score:', gsv.best_score_
        print '\n>>> Best Params:'
        pprint(gsv.best_params_)


class RandomForester(BaseEstimator, TransformerMixin):

    def __init__(self, num_features, n_estimators, max_depth=None, min_samples_split=2, n_jobs=20):
        """
        Constructor
        @param num_features:
            number of features. if in (0,1), represents the proportion of features. if >1,
            represents the final number of features.
        @param n_estimators, max_depth, min_samples_split, n_jobs: params used in ExtraTreesRegressor
        """

        self.num_features = num_features
        self.n_estimators = n_estimators
        self.max_depth = max_depth
        self.min_samples_split = min_samples_split
        self.n_jobs = n_jobs

        self._forest = ExtraTreesRegressor(n_estimators=self.n_estimators, max_depth=self.max_depth,
                                           min_samples_split=self.min_samples_split, n_jobs=self.n_jobs)

    def fit(self, X, y=None):
        """
        @return: self
        """

        self._forest.fit(X, y)

        return self

    def transform(self, X):
        """
        @return: new x
        """

        # importances = self._forest.feature_importances_
        num_features_to_use = int(self.num_features if self.num_features > 1 else np.shape(X)[1]*self.num_features)
        # indices = np.argsort(importances)[::-1][:num_features_to_use]

        indices, _, _ = self.top_indices(num_features_to_use)

        return X[:, indices]

    def fit_transform(self, X, y=None, **fit_params):
        """
        @return: new x
        """

        self.fit(X, y)

        return self.transform(X)

    def top_indices(self, num_features='auto', labels=None):
        """
        returns the top indices
        """

        n = self.__get_num_ticks(num_features)
        importances = self._forest.feature_importances_

        ind = np.argsort(importances)[::-1][:n]
        indLabels = None if labels is None else np.array(labels)[ind]

        return ind, indLabels, importances[ind]

    def __get_num_ticks(self, num_features):

        importances = self._forest.feature_importances_

        if num_features == 'auto':
            return int(self.num_features if self.num_features > 1 else len(importances) * self.num_features)
        elif num_features == 'all':
            return len(importances)
        elif isinstance(num_features, int):
            return num_features
        elif isinstance(num_features, float) and num_features > 0 and num_features < 1:
            print 'total importance =', np.sum(importances)
            numTicks = 0
            totalImp = 0
            for i in np.sort(importances)[::-1]:
                totalImp += i
                numTicks += 1
                if totalImp >= num_features:
                    break
            print 'Using %d features to achieve a total of %f importance.' % (numTicks, totalImp)
            return numTicks
        else:
            raise Exception('Invalid num_features provided:', num_features)

    def plot(self, num_features='auto', labels=None, title=None):
        """
        makes a bar plot of feature importances and corresp. standard deviations
        call only after the "fit" method has been called
        @param num_features:
            number of features to show.
              'auto': same as the class' number of  features
              'all': all features
              a number: specific # features
              a decimal: however many features it takes to sum up to that importance
        """

        importances = self._forest.feature_importances_

        numTicks = self.__get_num_ticks(num_features)

        indices = np.argsort(importances)[::-1][:numTicks]
        std = np.std([tree.feature_importances_ for tree in self._forest.estimators_], axis=0)

        plt.bar(range(len(indices)), importances[indices], color="r", yerr=std[indices], align="center")

        if labels is not None:
            plt.xticks(range(len(indices)), labels[indices], rotation=45)

        if title is not None:
            plt.title(title)

        plt.show()


def print_missing_values_info(data):
    """
    Prints the number of missing data columns and values of a pandas data frame.
    @param data 2D pandas data frame
    @return None
    """

    # -------- check na -----------
    temp_col = pandas.isnull(data).sum()
    temp_row = pandas.isnull(data).sum(axis=1)
    colsWithMissingData = list(data.columns[temp_col > 0])

    print '\n-------- OVERALL null -----------'
    print 'The data has', (temp_col > 0).sum(), 'or', round(100. * (temp_col > 0).sum() / data.shape[1], 1), '% columns (', colsWithMissingData, ') with missing values.'
    print 'The data has', (temp_row > 0).sum(), 'or', round(100. * (temp_row > 0).sum() / data.shape[0], 1), '% rows with missing values.'
    print 'The data has', temp_col.sum(), 'or', round(
        100. * temp_col.sum() / (data.shape[0] * data.shape[1]), 1), '% missing values.'

    print '\n-------- column-wise null -----------'
    print pandas.DataFrame({'count': list(temp_col), 'percentage': np.array(temp_col)*100./data.shape[0]}, index=temp_col.index)

    # -------- check inf -----------
    print '\n-------- column-wise inf -----------'
    for i in range(data.shape[1]):

        if data.icol(i).dtype=='object':
            print i, data.columns[i], 'skippped because it is of OBJECT type.'
            continue

        try:
            temp = np.isinf(list(np.array(data)[:, i])).sum()

            if temp > 0:
                print data.columns[i], 'has', temp, 'or', round(100.*temp/data.shape[0], 2), '% inf values.'
        except Exception as e:
            print i, data.columns[i], 'skippped due to an error:', e.message


def impute_field(inputTable, fieldName):
    """
    fieldName is the field to be imputed
    @param inputTable: a pandas data frame with fieldName and other features
    @return: X_present, y_present, X_missing, ind_

    missing
    """

    ind_missing = np.isnan(inputTable[fieldName])
    X_present = inputTable[-ind_missing]
    del X_present[fieldName]
    y_present = np.array(inputTable[-ind_missing][fieldName])  # use mode in case of multiple risk_factors per condensed row

    X_missing = inputTable[ind_missing]
    del X_missing[fieldName]

    return X_present, y_present, X_missing, ind_missing


def plot_feature_importances(X, Y, labels, numTopFeatures, numEstimators = 50, title = None, num_jobs = cpu_count()-1):
    """
    imputes and selects and plots the top features using random forest
    @param X: np.array
    """

    # impute missing data
    imp = Imputer()
    X = imp.fit_transform(X)

    rf = RandomForester(num_features = X.shape[1], n_estimators = numEstimators, n_jobs=num_jobs)
    rf.fit(X, Y)

    topFeatureInd, topFeatureLabels, topFeatureImportances = rf.top_indices(labels=labels, num_features=numTopFeatures)

    print 'Top features:'
    pprint(dict(zip(np.array(topFeatureLabels), np.array(topFeatureImportances))))

    rf.plot(num_features=numTopFeatures, labels=labels, title=title)

    return topFeatureInd, topFeatureLabels, topFeatureImportances